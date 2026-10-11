"""Durable mock provider; an accepted order settles independently of later security locks."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from banking_api.application.balance_service import AccountBalanceService
from banking_api.domain.enums import ApprovalStatus, ReauthenticationStatus
from banking_api.persistence.models import (
    ApprovalModel,
    NotificationModel,
    OperationModel,
    ReauthenticationModel,
    WorkflowModel,
)
from banking_api.runtime.event_publisher import EventPublisher
from banking_api.security.guard import SecurityGuardService, acquire_security_user_lock
from banking_api.wealth.calculation import WealthError, purchase, quantity, redeem, schedule, utc
from banking_api.wealth.catalog import digest
from banking_api.wealth.models import WealthHold, WealthLedger, WealthOrder, WealthPosition
from banking_api.wealth.service import WealthService


class MockWealthProvider:
    def __init__(
        self, session_factory, balances, clock=lambda: datetime.now(UTC), fault_mode="SUCCESS"
    ):
        self.session_factory, self.balances, self.clock = session_factory, balances, clock
        self.fault_mode = fault_mode
        self._locks = {}

    async def _locks_in_session(self, session, op):
        await acquire_security_user_lock(session, op.user_id)
        await session.get(WorkflowModel, op.workflow_id, with_for_update=True)
        await AccountBalanceService.serialize(session, op.payload_json["account_id"], op.user_id)

    async def submit(self, operation_id, user_id, direction):
        from banking_api.wealth.availability import mock_execution_allowed

        if not mock_execution_allowed():
            return {"outcome": "FAILED", "error_code": "WEALTH_DISABLED"}
        lock = self._locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            async with self.session_factory() as session:
                async with session.begin():
                    op = await session.get(OperationModel, operation_id)
                    if (
                        not op
                        or op.user_id != user_id
                        or op.operation_type.value != f"WEALTH_{direction}"
                    ):
                        return {"outcome": "FAILED", "error_code": "NOT_FOUND"}
                    await self._locks_in_session(session, op)
                    service = WealthService(session, self.balances, self.clock)
                    p = op.payload_json
                    position = await service.position(
                        user_id, p["account_id"], p["product_id"], lock=True
                    )
                    order = await session.scalar(
                        select(WealthOrder)
                        .where(WealthOrder.operation_id == operation_id)
                        .with_for_update()
                    )
                    if order:
                        return self.result(order, submit=True)
                    # Only persisted, consumed approval and its challenge confer authority.
                    a = await session.get(ApprovalModel, op.approval_id)
                    r = await session.scalar(
                        select(ReauthenticationModel).where(
                            ReauthenticationModel.approval_id == op.approval_id,
                            ReauthenticationModel.user_id == user_id,
                            ReauthenticationModel.status == ReauthenticationStatus.VERIFIED,
                        )
                    )
                    error = None
                    try:
                        from banking_api.wealth.availability import require_new_business

                        require_new_business()
                        await SecurityGuardService(session, clock=self.clock).require_write_allowed(
                            user_id
                        )
                        if (
                            not a
                            or a.user_id != user_id
                            or a.workflow_id != op.workflow_id
                            or a.status != ApprovalStatus.CONSUMED
                            or a.consumed_by_operation_id != op.operation_id
                            or a.payload_hash != digest(p)
                            or utc(a.expires_at) <= utc(self.clock())
                            or not r
                            or utc(r.expires_at) <= utc(self.clock())
                        ):
                            raise WealthError("AUTHORIZATION_EXPIRED", "授权已失效，订单未受理")
                        current = await service.version(p["product_id"])
                        if (
                            current.version_id != p["version_id"]
                            or schedule(self.clock(), p["terms"]["weekdays"], direction)[
                                "trade_date"
                            ]
                            != p["trade_date"]
                        ):
                            raise WealthError("AUTHORIZATION_EXPIRED", "交易日期或产品版本已变化")
                        value = quantity(p["quantity"], 2 if direction == "PURCHASE" else 6)
                        if direction == "PURCHASE":
                            assessment = await service.validate_purchase(
                                user_id, current, value, p["account_id"]
                            )
                            if str(assessment.assessment_id) != p["assessment_id"]:
                                raise WealthError("AUTHORIZATION_EXPIRED", "风险测评已变化")
                        elif (
                            not position
                            or position.shares
                            - await service.frozen(user_id, p["account_id"], p["product_id"])
                            < value
                        ):
                            raise WealthError("INSUFFICIENT_SHARES", "可赎回份额不足")
                        if self.fault_mode == "REJECT_BEFORE_ACCEPT":
                            raise WealthError("PROVIDER_REJECTED", "模拟受理前拒绝")
                    except WealthError as exc:
                        error = exc.code
                    except Exception as exc:
                        from banking_api.security.guard import SecurityWriteLockedError

                        if isinstance(exc, SecurityWriteLockedError):
                            error = "SECURITY_WRITE_LOCKED"
                        else:
                            raise
                    order = WealthOrder(
                        user_id=user_id,
                        workflow_id=op.workflow_id,
                        operation_id=operation_id,
                        idempotency_key=op.idempotency_key,
                        provider_reference=f"mockwealth_{uuid4().hex}",
                        direction=direction,
                        account_id=p["account_id"],
                        product_id=p["product_id"],
                        version_id=p["version_id"],
                        snapshot=p,
                        quantity=Decimal(p["quantity"]),
                        status="REJECTED" if error else "ACCEPTED",
                        error_code=error,
                        trade_date=date.fromisoformat(p["trade_date"]),
                        confirm_at=utc(datetime.fromisoformat(p["confirm_at"])),
                        settle_at=utc(datetime.fromisoformat(p["settle_at"])),
                        created_at=utc(self.clock()),
                    )
                    session.add(order)
                    await session.flush()
                    if not error:
                        session.add(
                            WealthHold(
                                order_id=order.order_id,
                                user_id=user_id,
                                account_id=order.account_id,
                                product_id=order.product_id,
                                kind="CASH" if direction == "PURCHASE" else "SHARES",
                                quantity=order.quantity,
                            )
                        )
                    await self.stage(session, order)
                    result = self.result(order, submit=True)
            if self.fault_mode == "TIMEOUT_AFTER_ACCEPT" and not error:
                return {"outcome": "UNKNOWN", "error_code": "SUBMISSION_AMBIGUOUS"}
            return result

    async def query(self, operation_id, user_id, direction):
        from banking_api.wealth.availability import mock_execution_allowed

        if not mock_execution_allowed():
            return {"status": "FAILED", "error_code": "WEALTH_DISABLED"}
        lock = self._locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            async with self.session_factory() as session:
                async with session.begin():
                    op = await session.get(OperationModel, operation_id)
                    if (
                        not op
                        or op.user_id != user_id
                        or op.operation_type.value != f"WEALTH_{direction}"
                    ):
                        return {"status": "UNKNOWN"}
                    await self._locks_in_session(session, op)
                    service = WealthService(session, self.balances, self.clock)
                    p = op.payload_json
                    position = await service.position(
                        user_id, p["account_id"], p["product_id"], lock=True
                    )
                    order = await session.scalar(
                        select(WealthOrder)
                        .where(WealthOrder.operation_id == operation_id)
                        .with_for_update()
                    )
                    if not order:
                        from banking_api.wealth.availability import feature_status

                        if not feature_status()["new_business_allowed"]:
                            return {"status": "FAILED", "error_code": "WEALTH_DISABLED"}
                        return {"status": "UNKNOWN"}
                    now = utc(self.clock())
                    if order.status == "ACCEPTED" and utc(order.confirm_at) <= now:
                        nav = await service.nav(order.product_id, order.trade_date)
                        if not nav:
                            return {
                                **self.result(order),
                                "next_reconcile_at": None,
                                "error_code": "NAV_MISSING",
                            }
                        try:
                            actual = (
                                purchase(
                                    order.quantity, nav.nav, Decimal(p["terms"]["purchase_rate"])
                                )
                                if direction == "PURCHASE"
                                else redeem(
                                    order.quantity, nav.nav, Decimal(p["terms"]["redeem_rate"])
                                )
                            )
                        except WealthError as exc:
                            # Explicit provider failure before any settlement mutation.
                            hold = await session.scalar(
                                select(WealthHold)
                                .where(WealthHold.order_id == order.order_id)
                                .with_for_update()
                            )
                            hold.active = False
                            order.status, order.error_code = "FAILED", exc.code
                            await self.stage(session, order)
                            return self.result(order)
                        order.actual = {k: str(v) for k, v in actual.items()} | {
                            "nav": str(nav.nav)
                        }
                        hold = await session.scalar(
                            select(WealthHold)
                            .where(WealthHold.order_id == order.order_id)
                            .with_for_update()
                        )
                        if not position:
                            position = WealthPosition(
                                user_id=user_id,
                                account_id=order.account_id,
                                product_id=order.product_id,
                                shares=Decimal(0),
                            )
                            session.add(position)
                        if direction == "PURCHASE":
                            position.shares += actual["shares"]
                            self.ledger(session, order, "PURCHASE_DEBIT", order.quantity)
                            self.ledger(session, order, "REFUND", actual["refund"])
                        else:
                            position.shares -= order.quantity
                        self.ledger(
                            session,
                            order,
                            "SHARES_IN" if direction == "PURCHASE" else "SHARES_OUT",
                            actual["shares"],
                        )
                        self.ledger(session, order, "FEE", actual["fee"])
                        hold.active = False
                        order.status = "CONFIRMED"
                        await self.stage(session, order)
                        if direction == "PURCHASE":
                            order.status = "SETTLED"
                            await self.stage(session, order)
                    if order.status == "CONFIRMED" and utc(order.settle_at) <= now:
                        self.ledger(session, order, "REDEEM_CREDIT", Decimal(order.actual["net"]))
                        order.status = "SETTLED"
                        await self.stage(session, order)
                    return self.result(order)

    def ledger(self, session, order, action, amount):
        session.add(
            WealthLedger(
                order_id=order.order_id,
                user_id=order.user_id,
                account_id=order.account_id,
                action=action,
                amount=amount,
                created_at=utc(self.clock()),
            )
        )

    async def stage(self, session, order):
        self.ledger(session, order, f"STAGE_{order.status}", Decimal(0))
        workflow = await session.get(WorkflowModel, order.workflow_id)
        labels = {
            "ACCEPTED": "已受理，待成交",
            "CONFIRMED": "已成交",
            "SETTLED": "最终完成",
            "REJECTED": "明确拒绝",
            "FAILED": "明确失败",
        }
        name = order.snapshot["name"]
        direction = "申购" if order.direction == "PURCHASE" else "赎回"
        title, message = (
            f"模拟理财{direction}{labels[order.status]}",
            f"{name}：{labels[order.status]}。",
        )
        if order.status == "SETTLED" and order.actual:
            if order.direction == "PURCHASE":
                message = f"{name}申购已完成，{Decimal(order.actual['shares']):,.6f}份已计入持仓。"
            else:
                message = (
                    f"{name}赎回款{Decimal(order.actual['net']):,.2f}元已到账，可在原付款账户查看。"
                )
        elif order.status == "CONFIRMED" and order.direction == "REDEEM":
            message = f"{name}赎回已成交，款项尚未到账；到账后会再次通知你。"
        session.add(
            NotificationModel(
                user_id=order.user_id,
                source_key=f"wealth:{order.order_id}:{order.status}",
                kind="WEALTH_RESULT",
                title=title,
                message=message,
                created_at=utc(self.clock()),
            )
        )
        await EventPublisher(session).persist(
            event_type=f"wealth.order.{order.status.lower()}",
            conversation_id=workflow.conversation_id,
            task_id=workflow.source_task_id,
            data={
                "order_id": str(order.order_id),
                "workflow_id": str(order.workflow_id),
                "operation_id": str(order.operation_id),
                "stage": order.status,
                "actual": order.actual,
                "trade_date": order.trade_date.isoformat(),
                **{f"actual_{k}": v for k, v in (order.actual or {}).items()},
            },
        )

    @staticmethod
    def result(order, submit=False):
        failed = order.status in {"FAILED", "REJECTED"}
        return {
            ("outcome" if submit else "status"): (
                "FAILED"
                if failed
                else "ACCEPTED"
                if submit
                else "SUCCEEDED"
                if order.status == "SETTLED"
                else "PENDING"
            ),
            "provider_reference": order.provider_reference,
            "error_code": order.error_code,
            "next_reconcile_at": (
                order.settle_at if order.status == "CONFIRMED" else order.confirm_at
            ).isoformat()
            if order.status in {"ACCEPTED", "CONFIRMED"}
            else None,
        }
