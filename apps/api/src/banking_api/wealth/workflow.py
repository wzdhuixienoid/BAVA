"""Deterministic purchase/redeem workflows using canonical Approval and Reauthentication."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from banking_api.config.settings import get_settings
from banking_api.domain.approval import ApprovalType
from banking_api.domain.enums import (
    ApprovalStatus,
    OperationStatus,
    ReauthenticationStatus,
    WorkflowStatus,
)
from banking_api.domain.operation import OperationType
from banking_api.domain.workflow import WorkflowType
from banking_api.mock_bank.service import AccountNotFoundError
from banking_api.persistence.models import OperationModel
from banking_api.persistence.repositories.approvals import ApprovalRepository
from banking_api.persistence.repositories.conversations import ConversationRepository
from banking_api.persistence.repositories.reauthentications import ReauthenticationRepository
from banking_api.persistence.repositories.workflows import WorkflowRepository
from banking_api.runtime.event_publisher import EventPublisher
from banking_api.security.guard import SecurityGuardService, acquire_security_user_lock
from banking_api.security.reauthentication.mock_provider import MockReauthenticationProvider
from banking_api.wealth.calculation import WealthError, purchase, quantity, redeem, schedule, utc
from banking_api.wealth.catalog import digest
from banking_api.wealth.schemas import WealthRiskDecision
from banking_api.wealth.service import WealthService

TYPES = {WorkflowType.WEALTH_PURCHASE, WorkflowType.WEALTH_REDEEM}


class WealthWorkflow:
    direction = None

    def __init__(self, session, balances, clock=lambda: datetime.now(UTC), reauth_provider=None):
        self.session, self.balances, self.clock = session, balances, clock
        self.service = WealthService(session, balances, clock)
        self.publisher = EventPublisher(session)
        self.settings = get_settings()
        self.reauth_provider = reauth_provider or MockReauthenticationProvider(
            self.settings.mock_reauth_code
        )

    async def load(self, workflow_id, user_id, expected_version=None):
        from banking_api.application.workflow_service import (
            WorkflowNotFoundError,
            WorkflowVersionConflictError,
        )

        await acquire_security_user_lock(self.session, user_id)
        model = await WorkflowRepository(self.session).get_for_user_for_update(workflow_id, user_id)
        if (
            not model
            or model.workflow_type not in TYPES
            or (self.direction and model.workflow_type.value != f"WEALTH_{self.direction}")
        ):
            raise WorkflowNotFoundError
        if expected_version is not None and model.version != expected_version:
            raise WorkflowVersionConflictError
        return model

    async def event(self, model, kind):
        a = await ApprovalRepository(self.session).latest_for_workflow(
            model.workflow_id, model.user_id
        )
        r = await ReauthenticationRepository(self.session).latest_for_workflow(
            model.workflow_id, model.user_id
        )
        review = model.state_json.get("review") or {}
        data = {
            "workflow_id": str(model.workflow_id),
            "workflow_type": model.workflow_type.value,
            "status": model.status.value,
            "version": model.version,
            "trade_date": review.get("trade_date"),
            "wealth_risk_decision": self.risk_decision(review),
        }
        if a:
            data.update(
                approval_id=str(a.approval_id),
                payload_hash=a.payload_hash,
                expires_at=a.expires_at.isoformat(),
            )
        if r:
            data.update(reauth_id=str(r.reauth_id))
        await self.publisher.persist(
            event_type=kind,
            conversation_id=model.conversation_id,
            task_id=model.source_task_id,
            data=data,
        )

    async def resolve_draft(self, user_id, draft):
        draft = dict(draft)
        if draft.get("redeem_all") and draft["direction"] == "REDEEM":
            positions = [
                p
                for p in await self.service.positions(user_id)
                if (not draft.get("product_id") or p.product_id == draft["product_id"])
                and (not draft.get("account_id") or p.account_id == draft["account_id"])
            ]
            if not positions:
                raise WealthError("INSUFFICIENT_SHARES", "没有对应持仓或可赎回份额")
            if len(positions) == 1:
                p = positions[0]
                if Decimal(p.available_quantity) <= 0:
                    raise WealthError("INSUFFICIENT_SHARES", "没有可赎回份额，不能全部赎回")
                quantity(p.available_quantity, 6)
                draft.update(
                    product_id=p.product_id,
                    account_id=p.account_id,
                    quantity=p.available_quantity,
                    quantity_unit="份",
                    redeem_all=False,
                )
            else:
                draft["quantity_message"] = "全部赎回需先唯一确定产品和本人原付款账户"
        expected = "元" if draft["direction"] == "PURCHASE" else "份"
        if draft.get("quantity") is not None and draft.get("quantity_unit", expected) != expected:
            draft["quantity"] = None
            draft["quantity_message"] = f"请补充单位为{expected}的交易数量"
        return draft

    async def review(self, user_id, draft):
        if not all(draft.get(k) for k in ("product_id", "account_id", "quantity")):
            return None
        direction = draft["direction"]
        value = quantity(draft["quantity"], 2 if direction == "PURCHASE" else 6)
        try:
            account = self.balances._bank.get_balance(draft["account_id"], user_id=user_id)
        except (ValueError, KeyError, AccountNotFoundError):
            raise WealthError("NOT_FOUND", "未找到本人账户") from None
        eligible = next(
            (
                a
                for a in self.balances._bank.list_accounts(user_id=user_id)
                if a["account_id"] == draft["account_id"]
            ),
            None,
        )
        if (
            not eligible
            or eligible["status"] != "ACTIVE"
            or eligible["account_type"] not in {"DEBIT", "SAVINGS"}
        ):
            raise WealthError("ACCOUNT_NOT_ELIGIBLE", "请使用本人有效储蓄或借记账户")
        if account["currency"] != "CNY":
            raise WealthError("CURRENCY_UNSUPPORTED", "理财仅支持人民币本人账户")
        v = await self.service.version(draft["product_id"])
        assessment = None
        if direction == "PURCHASE":
            assessment = await self.service.validate_purchase(
                user_id, v, value, draft["account_id"]
            )
        else:
            position = await self.service.position(
                user_id, draft["account_id"], draft["product_id"]
            )
            if (
                not position
                or position.shares
                - await self.service.frozen(user_id, draft["account_id"], draft["product_id"])
                < value
            ):
                raise WealthError("INSUFFICIENT_SHARES", "本人原付款账户对应的可赎回份额不足")
        nav = await self.service.nav(v.product_id)
        if not nav:
            raise WealthError("NAV_MISSING", "缺少已发布净值，暂不能核对交易")
        estimate = (
            purchase(value, nav.nav, Decimal(v.terms["purchase_rate"]))
            if direction == "PURCHASE"
            else redeem(value, nav.nav, Decimal(v.terms["redeem_rate"]))
        )
        sources = [d.source for d in await self.service.documents(v)]
        dates = schedule(self.clock(), v.terms["weekdays"], direction)
        return {
            **draft,
            **dates,
            "version_id": v.version_id,
            "name": v.name,
            "account_display": account["display_name"],
            "account_masked": account["masked_number"],
            "terms": v.terms,
            "risk": v.risk,
            "sources": sources,
            "assessment_id": str(assessment.assessment_id) if assessment else None,
            "customer_grade": f"C{assessment.grade}" if assessment else None,
            "estimate": {k: str(v) for k, v in estimate.items()},
            "estimated_nav": str(nav.nav),
            "quantity_display": f"{value:,.2f} 元"
            if direction == "PURCHASE"
            else f"{value:.6f} 份",
            "fee_display": f"{estimate['fee']:,.2f} 元（估算）",
            "net_display": f"{estimate['net']:,.2f} 元（估算）",
            "shares_display": f"{estimate['shares']:.6f} 份（估算）",
            "notice": (
                "按未来交易日净值成交，费用、份额及到账金额为估算；成交后以实际账本为准。"
                "无本金或收益保证。受理后不可撤单。"
            ),
        }

    @staticmethod
    def risk_decision(review):
        review = review or {}
        return WealthRiskDecision(
            assessment_id=review.get("assessment_id"),
            customer_grade=review.get("customer_grade"),
            product_risk=review.get("risk"),
            reasons=["所有申购与赎回均需确认和强验证；申购需有效适当性证据"],
        ).model_dump(mode="json")

    def require_enabled(self):
        from banking_api.wealth.availability import require_new_business

        require_new_business()

    async def create(
        self, user_id, conversation_id, source_task_id, draft, allow_invalid_draft=False
    ):
        self.require_enabled()
        if self.direction and draft["direction"] != self.direction:
            raise WealthError("DIRECTION_MISMATCH", "交易方向与工作流不匹配")
        from banking_api.persistence.models import TaskModel

        conversation = await ConversationRepository(self.session).get_for_user(
            conversation_id, user_id
        )
        task = await self.session.get(TaskModel, source_task_id)
        if (
            not conversation
            or not task
            or task.user_id != user_id
            or task.conversation_id != conversation_id
        ):
            raise WealthError("NOT_FOUND", "未找到本人对话与任务")
        old = await WorkflowRepository(self.session).get_by_source_task(source_task_id, user_id)
        if old:
            return old
        # Assessment is an entry prerequisite, not an optional draft field.
        # Never let allow_invalid_draft turn missing/expired evidence into a purchase card.
        if draft["direction"] == "PURCHASE":
            await self.service.require_assessment(user_id)
        validation_message = None
        try:
            draft = await self.resolve_draft(user_id, draft)
            review = await self.review(user_id, draft)
        except WealthError as exc:
            if not allow_invalid_draft:
                raise
            review, validation_message = None, str(exc)
        model = await WorkflowRepository(self.session).create(
            user_id=user_id,
            conversation_id=conversation_id,
            source_task_id=source_task_id,
            workflow_type=WorkflowType(f"WEALTH_{draft['direction']}"),
            status=WorkflowStatus.READY_FOR_REVIEW if review else WorkflowStatus.WAITING_FOR_INPUT,
            state={
                "draft": draft,
                "review": review,
                "wealth_risk": self.risk_decision(review),
                "validation_message": draft.get("quantity_message") or validation_message,
            },
        )
        await self.event(model, "workflow.created")
        return model

    async def invalidate(self, model):
        await ApprovalRepository(self.session).invalidate_active(
            model.workflow_id, model.user_id, self.clock()
        )
        await ReauthenticationRepository(self.session).invalidate_active(
            model.workflow_id, model.user_id, self.clock()
        )

    async def edit(self, workflow_id, user_id, body):
        self.require_enabled()
        model = await self.load(workflow_id, user_id, body.expected_version)
        await SecurityGuardService(self.session, clock=self.clock).require_write_allowed(
            user_id=user_id
        )
        if model.status in {
            WorkflowStatus.COMMITTING,
            WorkflowStatus.SUCCEEDED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        }:
            raise WealthError("ORDER_NOT_CANCELLABLE", "已提交或已结束的订单不能修改")
        draft = {
            **model.state_json["draft"],
            **body.model_dump(exclude_none=True, exclude={"expected_version"}),
        }
        if body.quantity is not None:
            draft["quantity_unit"] = "元" if draft["direction"] == "PURCHASE" else "份"
            draft["quantity_message"] = None
            quantity(draft["quantity"], 2 if draft["direction"] == "PURCHASE" else 6)
        draft = await self.resolve_draft(user_id, draft)
        review = await self.review(user_id, draft)
        await self.invalidate(model)
        model.state_json = {
            "draft": draft,
            "review": review,
            "wealth_risk": self.risk_decision(review),
        }
        model.status = (
            WorkflowStatus.READY_FOR_REVIEW if review else WorkflowStatus.WAITING_FOR_INPUT
        )
        model.version += 1
        await self.event(model, "workflow.updated")
        await self.session.commit()
        return model

    async def authorization(self, model, consumed=False):
        approval = await ApprovalRepository(self.session).latest_for_workflow(
            model.workflow_id, model.user_id
        )
        expected = ApprovalStatus.CONSUMED if consumed else ApprovalStatus.APPROVED
        if (
            not approval
            or approval.status != expected
            or utc(approval.expires_at) <= utc(self.clock())
            or approval.payload_hash != digest(model.state_json["review"])
        ):
            raise WealthError("AUTHORIZATION_EXPIRED", "确认已失效，请重新核对并确认")
        return approval

    async def action(
        self, workflow_id, user_id, expected_version, action, reauth_id=None, verification_code=None
    ):
        model = await self.load(workflow_id, user_id, expected_version)
        await SecurityGuardService(self.session, clock=self.clock).require_write_allowed(
            user_id=user_id
        )
        if action != "cancel":
            self.require_enabled()
        now = utc(self.clock())
        state = dict(model.state_json)
        if action == "cancel":
            if model.status in {
                WorkflowStatus.COMMITTING,
                WorkflowStatus.SUCCEEDED,
                WorkflowStatus.FAILED,
                WorkflowStatus.CANCELLED,
            }:
                raise WealthError("ORDER_NOT_CANCELLABLE", "订单已受理或结束，不能取消")
            await self.invalidate(model)
            model.status = WorkflowStatus.CANCELLED
            from banking_api.domain.enums import TaskStatus
            from banking_api.persistence.models import TaskModel

            task = await self.session.get(TaskModel, model.source_task_id)
            task.status = TaskStatus.CANCELLED
            task.version += 1
        elif action == "approve":
            if model.status not in {
                WorkflowStatus.READY_FOR_REVIEW,
                WorkflowStatus.REAUTH_REQUIRED,
                WorkflowStatus.READY_FOR_COMMIT,
            }:
                raise WealthError("WORKFLOW_NOT_READY", "请先补全交易资料")
            fresh = await self.review(user_id, state["draft"])
            if fresh != state["review"]:
                await self.invalidate(model)
                model.state_json = {**state, "review": fresh}
                model.status = WorkflowStatus.READY_FOR_REVIEW
                model.version += 1
                await self.event(model, "workflow.updated")
                await self.session.commit()
                raise WealthError(
                    "AUTHORIZATION_EXPIRED", "核对内容已变化，请查看新日期及估算后再次确认"
                )
            state["review"] = fresh
            model.state_json = state
            await self.invalidate(model)
            a = await ApprovalRepository(self.session).create_pending(
                user_id=user_id,
                workflow_id=model.workflow_id,
                payload=state["review"],
                payload_hash=digest(state["review"]),
                approval_type=ApprovalType(model.workflow_type.value),
                expires_at=now + timedelta(seconds=self.settings.transfer_approval_ttl_seconds),
            )
            a.status, a.approved_at = ApprovalStatus.APPROVED, now
            model.status = WorkflowStatus.REAUTH_REQUIRED
            await self.event(model, "approval.approved")
        elif action == "start-reauth":
            if model.status != WorkflowStatus.REAUTH_REQUIRED:
                raise WealthError("REAUTH_NOT_REQUIRED", "请先确认交易")
            a = await self.authorization(model)
            await ReauthenticationRepository(self.session).invalidate_active(
                model.workflow_id, user_id, self.clock()
            )
            challenge = await self.reauth_provider.start_challenge(
                user_id=user_id, workflow_id=model.workflow_id, approval_id=a.approval_id
            )
            await ReauthenticationRepository(self.session).create(
                user_id=user_id,
                workflow_id=model.workflow_id,
                approval_id=a.approval_id,
                method=challenge.method,
                provider_reference=challenge.provider_reference,
                expires_at=now + timedelta(seconds=self.settings.transfer_reauth_ttl_seconds),
            )
            await self.event(model, "reauth.challenge.created")
        elif action == "verify-reauth":
            if model.status != WorkflowStatus.REAUTH_REQUIRED:
                raise WealthError("REAUTH_NOT_PENDING", "当前没有待完成的强验证")
            a = await self.authorization(model)
            r = await ReauthenticationRepository(self.session).latest_for_workflow(
                model.workflow_id, user_id
            )
            if (
                not r
                or r.reauth_id != reauth_id
                or r.approval_id != a.approval_id
                or r.status != ReauthenticationStatus.PENDING
                or utc(r.expires_at) <= now
            ):
                raise WealthError("AUTHORIZATION_EXPIRED", "强验证已失效，请重新开始")
            ok = await self.reauth_provider.verify(
                user_id=user_id,
                workflow_id=model.workflow_id,
                approval_id=a.approval_id,
                provider_reference=r.provider_reference,
                verification_code=verification_code,
            )
            r.attempt_count += 1
            await SecurityGuardService(
                self.session, clock=self.clock
            ).record_reauthentication_result(
                user_id=user_id,
                workflow_id=model.workflow_id,
                conversation_id=model.conversation_id,
                task_id=model.source_task_id,
                succeeded=ok,
            )
            if not ok:
                if r.attempt_count >= self.settings.transfer_reauth_max_attempts:
                    r.status = ReauthenticationStatus.FAILED
                model.version += 1
                await self.event(model, "reauth.failed")
                await self.session.commit()
                raise WealthError("REAUTH_FAILED", "验证码错误，验证未通过")
            r.status, r.verified_at = ReauthenticationStatus.VERIFIED, now
            model.status = WorkflowStatus.READY_FOR_COMMIT
            await self.event(model, "reauth.verified")
        else:
            raise WealthError("ACTION_INVALID", "不支持的理财动作")
        model.version += 1
        await self.event(model, "workflow.updated")
        await self.session.commit()
        return model

    async def prepare(self, workflow_id, user_id, expected_version):
        # Same global order as other write paths: Security -> Workflow -> Account.
        await acquire_security_user_lock(self.session, user_id)
        old = await self.session.scalar(
            select(OperationModel).where(
                OperationModel.workflow_id == workflow_id, OperationModel.user_id == user_id
            )
        )
        if old:
            await self.session.commit()
            return old
        self.require_enabled()
        model = await self.load(workflow_id, user_id, expected_version)
        await SecurityGuardService(self.session, clock=self.clock).require_write_allowed(
            user_id=user_id
        )
        if model.status != WorkflowStatus.READY_FOR_COMMIT:
            await SecurityGuardService(
                self.session, clock=self.clock
            ).record_control_bypass_attempt(
                user_id=user_id,
                workflow_id=model.workflow_id,
                conversation_id=model.conversation_id,
                task_id=model.source_task_id,
            )
            await self.session.commit()
            raise WealthError("AUTHORIZATION_REQUIRED", "交易需用户确认及强验证")
        a = await self.authorization(model)
        r = await ReauthenticationRepository(self.session).latest_for_workflow(workflow_id, user_id)
        if (
            not r
            or r.approval_id != a.approval_id
            or r.status != ReauthenticationStatus.VERIFIED
            or utc(r.expires_at) <= utc(self.clock())
        ):
            raise WealthError("AUTHORIZATION_EXPIRED", "强验证已失效，请重新验证")
        fresh = await self.review(user_id, model.state_json["draft"])
        # NAV estimates may move; dates, terms and assessment cannot move silently.
        keys = ("trade_date", "confirm_at", "settle_at", "version_id", "terms", "assessment_id")
        if any(fresh[k] != model.state_json["review"][k] for k in keys):
            await self.invalidate(model)
            model.state_json = {**model.state_json, "review": fresh}
            model.status = WorkflowStatus.READY_FOR_REVIEW
            model.version += 1
            await self.event(model, "workflow.updated")
            await self.session.commit()
            raise WealthError(
                "AUTHORIZATION_EXPIRED", "日期、产品或测评已变化，请重新核对、确认和强验证"
            )
        op = OperationModel(
            user_id=user_id,
            workflow_id=workflow_id,
            approval_id=a.approval_id,
            operation_type=OperationType(model.workflow_type.value),
            payload_json=a.payload_json,
            payload_hash=a.payload_hash,
            idempotency_key=uuid4(),
            status=OperationStatus.CREATED,
            version=1,
            next_reconcile_at=self.clock(),
            reconcile_attempts=0,
        )
        self.session.add(op)
        await self.session.flush()
        a.status, a.consumed_at, a.consumed_by_operation_id = (
            ApprovalStatus.CONSUMED,
            self.clock(),
            op.operation_id,
        )
        model.status = WorkflowStatus.COMMITTING
        model.version += 1
        await self.event(model, "approval.consumed")
        await self.event(model, "operation.created")
        await self.session.commit()  # End application snapshot before provider I/O.
        return op


class WealthPurchaseWorkflow(WealthWorkflow):
    direction = "PURCHASE"


class WealthRedeemWorkflow(WealthWorkflow):
    direction = "REDEEM"


def wealth_workflow(
    direction, session, balances, clock=lambda: datetime.now(UTC), reauth_provider=None
):
    cls = WealthPurchaseWorkflow if direction == "PURCHASE" else WealthRedeemWorkflow
    return cls(session, balances, clock, reauth_provider)
