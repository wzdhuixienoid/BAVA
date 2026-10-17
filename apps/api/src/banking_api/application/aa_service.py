"""Station-local Mock collections. Publishing never grants another person's payment."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from banking_api.application.conversation_service import ConversationService
from banking_api.application.operation_service import OperationActionError, _as_utc
from banking_api.application.workflow_service import WorkflowService
from banking_api.domain.enums import (
    ExecutorType,
    MessageRole,
    OperationStatus,
    RequestedOutput,
    TaskStatus,
    WorkflowStatus,
)
from banking_api.persistence.models import (
    AARequestModel,
    AAShareModel,
    OperationModel,
    WorkflowModel,
)
from banking_api.runtime.event_publisher import EventPublisher
from banking_api.security.guard import SecurityGuardService, acquire_security_user_lock
from banking_api.workflows.transfer.models import Remark, TransferIntent

# Synthetic identities, provisioned solely at the development authentication boundary.
MOCK_PARTICIPANTS = {"张三": "mock-zhangsan", "李四": "mock-lisi", "王五": "mock-wangwu"}


class AAIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total: Decimal | None = None
    currency: str | None = None
    participants: list[str] = Field(default_factory=list, max_length=20)
    initiator_participates: bool | None = None
    source_account_hint: str | None = None
    remark: Remark = ""
    manual_amounts: dict[str, Decimal] | None = None

    @field_validator("total", mode="before")
    @classmethod
    def exact_total(cls, value):
        if value is not None and not isinstance(value, (str, Decimal)):
            raise ValueError("total requires a decimal string")
        return value

    @field_validator("manual_amounts", mode="before")
    @classmethod
    def exact_manual(cls, value):
        if value is not None and any(not isinstance(v, (str, Decimal)) for v in value.values()):
            raise ValueError("manual amounts require decimal strings")
        return value


class AAUpdate(BaseModel):
    expected_version: int
    intent: AAIntent
    collection_account_id: str | None = None
    deadline: datetime | None = None


class AAAction(BaseModel):
    expected_version: int


class AAPaymentAction(BaseModel):
    expected_version: int
    source_account_id: str


def cents(value: Decimal) -> int:
    if (
        not value.is_finite()
        or value <= 0
        or value.as_tuple().exponent < -2
        or value > Decimal("10000000")
    ):
        raise OperationActionError("AA_AMOUNT_INVALID")
    return int(value * 100)


def split_cents(total: Decimal, names: list[str], manual: dict[str, Decimal] | None) -> list[int]:
    total_cents = cents(total)
    if not names or len(set(names)) != len(names):
        raise OperationActionError("AA_PARTICIPANTS_INVALID")
    if manual is not None:
        if set(manual) != set(names):
            raise OperationActionError("AA_MANUAL_PARTICIPANTS_MISMATCH")
        amounts = [cents(manual[name]) for name in names]
        if sum(amounts) != total_cents:
            raise OperationActionError("AA_MANUAL_TOTAL_MISMATCH")
        return amounts
    quotient, remainder = divmod(total_cents, len(names))
    if quotient == 0:
        raise OperationActionError("AA_ZERO_SHARE")
    return [quotient + (index < remainder) for index in range(len(names))]


def money(value: int) -> str:
    return format(Decimal(value) / 100, ".2f")


class AAService:
    def __init__(self, session, bus, engine, bank, *, clock=lambda: datetime.now(UTC)):
        self.session, self.bus, self.engine, self.bank, self.clock = (
            session,
            bus,
            engine,
            bank,
            clock,
        )

    async def create(self, *, user_id, conversation_id, source_task_id, intent: AAIntent):
        existing = await self.session.scalar(
            select(AARequestModel).where(
                AARequestModel.source_task_id == source_task_id, AARequestModel.user_id == user_id
            )
        )
        if existing:
            return await self.resource(existing, user_id)
        await SecurityGuardService(self.session).require_write_allowed(user_id)
        row = AARequestModel(
            user_id=user_id,
            conversation_id=conversation_id,
            source_task_id=source_task_id,
            draft_json={"intent": intent.model_dump(mode="json"), "collection_account_id": None},
            deadline=self.clock() + timedelta(days=7),
        )
        if intent.source_account_hint:
            options = [
                a
                for a in self.bank.list_accounts(user_id=user_id)
                if a["display_name"] == intent.source_account_hint
            ]
            if len(options) == 1:
                row.draft_json["collection_account_id"] = options[0]["account_id"]
        self.session.add(row)
        await self.session.flush()
        await self._event(row, "aa.created")
        await self.session.commit()
        return await self.resource(row, user_id)

    async def _owned(self, request_id, user_id, *, issuer=False, lock=False):
        row = await self.session.get(
            AARequestModel, request_id, with_for_update=lock, populate_existing=lock
        )
        if row is None:
            raise OperationActionError("AA_NOT_FOUND")
        if row.user_id != user_id:
            if (
                issuer
                or await self.session.scalar(
                    select(AAShareModel.share_id).where(
                        AAShareModel.request_id == request_id, AAShareModel.user_id == user_id
                    )
                )
                is None
            ):
                raise OperationActionError("AA_NOT_FOUND")
        return row

    async def update(self, request_id, user_id, body: AAUpdate):
        await SecurityGuardService(self.session).require_write_allowed(user_id)
        row = await self._owned(request_id, user_id, issuer=True, lock=True)
        self._version(row, body.expected_version)
        if row.status != "DRAFT":
            raise OperationActionError("AA_PUBLISHED_SNAPSHOT_IMMUTABLE_CREATE_NEW_REQUEST")
        row.draft_json = {
            "intent": body.intent.model_dump(mode="json"),
            "collection_account_id": body.collection_account_id,
        }
        if body.deadline:
            if body.deadline.tzinfo is None:
                raise OperationActionError("AA_DEADLINE_REQUIRES_TIMEZONE")
            row.deadline = body.deadline.astimezone(UTC)
        row.version += 1
        await self._event(row, "aa.draft.updated")
        await self.session.commit()
        return await self.resource(row, user_id)

    @staticmethod
    def _version(row, expected):
        if row.version != expected:
            raise OperationActionError("AA_VERSION_CONFLICT")

    def preview(self, row):
        intent = AAIntent.model_validate(row.draft_json["intent"])
        if intent.total is None or intent.initiator_participates is None or not intent.participants:
            raise OperationActionError("AA_COMPLETE_TOTAL_PARTICIPANTS_AND_SELF_PARTICIPATION")
        if intent.currency and intent.currency.upper() != "CNY":
            raise OperationActionError("AA_CURRENCY_UNSUPPORTED")
        names = [name.strip() for name in intent.participants]
        if any(
            name not in MOCK_PARTICIPANTS or MOCK_PARTICIPANTS[name] == row.user_id
            for name in names
        ):
            raise OperationActionError("AA_PARTICIPANT_NOT_REGISTERED_OR_SELF")
        if intent.initiator_participates:
            names.append("我")
        amounts = split_cents(intent.total, names, intent.manual_amounts)
        account = next(
            (
                a
                for a in self.bank.list_accounts(user_id=row.user_id)
                if a["account_id"] == row.draft_json.get("collection_account_id")
                and a["status"] == "ACTIVE"
                and a["currency"] == "CNY"
                and a["account_type"] in {"DEBIT", "SAVINGS"}
            ),
            None,
        )
        if account is None:
            raise OperationActionError("AA_COLLECTION_ACCOUNT_REQUIRED")
        if row.deadline is None or _as_utc(row.deadline) <= _as_utc(self.clock()):
            raise OperationActionError("AA_DEADLINE_PAST")
        return {
            "total": money(sum(amounts)),
            "currency": "CNY",
            "remark": intent.remark,
            "collection_account": account,
            "destination_user_id": row.user_id,
            "deadline": _as_utc(row.deadline).isoformat(),
            "initiator_participates": intent.initiator_participates,
            "participants": [
                {
                    "user_id": row.user_id if name == "我" else MOCK_PARTICIPANTS[name],
                    "display_name": name,
                    "amount": money(amount),
                    "amount_cents": amount,
                    "self_paid": name == "我",
                }
                for name, amount in zip(names, amounts, strict=True)
            ],
        }

    async def publish(self, request_id, user_id, expected_version):
        await SecurityGuardService(self.session).require_write_allowed(user_id)
        row = await self._owned(request_id, user_id, issuer=True, lock=True)
        self._version(row, expected_version)
        if row.status != "DRAFT":
            raise OperationActionError("AA_ALREADY_PUBLISHED")
        snapshot = self.preview(row)
        row.snapshot_json = snapshot
        row.payload_hash = hashlib.sha256(
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        row.status, row.version = "PUBLISHED", row.version + 1
        for index, item in enumerate(snapshot["participants"]):
            self.session.add(
                AAShareModel(
                    request_id=row.request_id,
                    user_id=item["user_id"],
                    display_name=item["display_name"],
                    position=index,
                    amount_cents=item["amount_cents"],
                    status="SELF_PAID" if item["self_paid"] else "PENDING",
                )
            )
        await self._event(row, "aa.published")
        await self.session.commit()
        return await self.resource(row, user_id)

    async def resolve_payment(self, *, share_id, user_id):
        share = await self.session.get(AAShareModel, share_id)
        if (
            share is None
            or share.user_id != user_id
            or share.status != "PENDING"
            or share.operation_id
        ):
            return None
        row = await self.session.get(AARequestModel, share.request_id)
        if _as_utc(row.deadline) <= _as_utc(self.clock()) or not row.snapshot_json:
            return None
        snapshot = row.snapshot_json
        target = snapshot["collection_account"]
        current = next(
            (
                a
                for a in self.bank.list_accounts(user_id=row.user_id)
                if a["account_id"] == target["account_id"]
                and a["status"] == "ACTIVE"
                and a["currency"] == "CNY"
            ),
            None,
        )
        if current is None:
            return None
        return {
            "request_id": row.request_id,
            "amount": money(share.amount_cents),
            "remark": snapshot["remark"],
            "destination_user_id": row.user_id,
            "destination_account_id": target["account_id"],
            "payee": {
                "payee_id": f"aa:{share.share_id}",
                "display_name": "AA 发起者",
                "bank_name": "站内 Mock 银行",
                "masked_account": target["masked_number"],
                "phone_alias": "站内请求",
                "status": "ACTIVE",
            },
        }

    async def payment(self, share_id, user_id, expected_version, account_id):
        share = await self.session.get(AAShareModel, share_id)
        if share is None or share.user_id != user_id:
            raise OperationActionError("AA_SHARE_NOT_FOUND")
        await SecurityGuardService(self.session).require_write_allowed(user_id)
        row = await self.session.get(AARequestModel, share.request_id)
        self._version(row, expected_version)
        if share.workflow_id:
            return await WorkflowService(self.session, self.bus, self.engine).get(
                share.workflow_id, user_id=user_id
            )
        if share.status != "PENDING" or row.deleted_at is not None:
            raise OperationActionError("AA_SHARE_NOT_PAYABLE")
        # Prepare an owned conversation and task before locking.
        conv = await ConversationService(self.session, self.bus).create(
            user_id=user_id, title="AA 付款"
        )
        await acquire_security_user_lock(self.session, user_id)
        share = await self.session.get(
            AAShareModel, share_id, with_for_update=True, populate_existing=True
        )
        if share.workflow_id:
            return await WorkflowService(self.session, self.bus, self.engine).get(
                share.workflow_id, user_id=user_id
            )
        target = await self.resolve_payment(share_id=share_id, user_id=user_id)
        if target is None:
            raise OperationActionError("AA_SHARE_NOT_PAYABLE")
        account = next(
            (a for a in self.bank.list_accounts(user_id=user_id) if a["account_id"] == account_id),
            None,
        )
        if account is None:
            raise OperationActionError("AA_SOURCE_ACCOUNT_NOT_OWNED")
        # A participant action is already a deterministic request with an immutable AA target.
        # Publish its Task and Workflow atomically; never expose a runnable PENDING Task
        # that the general TaskRunner could independently interpret as another payment.
        from banking_api.persistence.repositories.messages import MessageRepository
        from banking_api.persistence.repositories.tasks import TaskRepository

        message = await MessageRepository(self.session).create(
            conversation_id=conv.conversation_id,
            role=MessageRole.USER,
            content="核对并支付我的 AA 份额",
        )
        task = await TaskRepository(self.session).create(
            conversation_id=conv.conversation_id,
            user_id=user_id,
            task_type="aa_share_payment",
            input_data={"message_id": str(message.message_id), "request_id": str(uuid4())},
        )
        task.status, task.next_run_at = TaskStatus.COMPLETED, None
        task.executor_type, task.executor_id, task.requested_output = (
            ExecutorType.WORKFLOW,
            "workflow:transfer",
            RequestedOutput.WORKFLOW,
        )
        workflow = await WorkflowService(self.session, self.bus, self.engine).create_transfer(
            user_id=user_id,
            conversation_id=conv.conversation_id,
            source_task_id=task.task_id,
            intent=TransferIntent(
                amount=target["amount"],
                currency="CNY",
                remark=target["remark"],
                source_account_hint=account["display_name"],
            ),
            aa_share_id=share_id,
            commit=False,
        )
        share.workflow_id = workflow.workflow_id
        task.output_json = {
            "workflow_id": str(workflow.workflow_id),
            "aa_request_id": str(row.request_id),
            "aa_share_id": str(share_id),
        }
        await EventPublisher(self.session).persist(
            event_type="task.completed",
            conversation_id=conv.conversation_id,
            task_id=task.task_id,
            data={
                "status": "COMPLETED",
                "workflow_id": str(workflow.workflow_id),
                "aa_request_id": str(row.request_id),
                "aa_share_id": str(share_id),
            },
        )
        await self._event(row, "aa.payment.workflow.created", share)
        await self.session.commit()
        return workflow

    async def close_share(self, share_id, user_id, expected_version, *, reject=False):
        share = await self.session.get(AAShareModel, share_id)
        if share is None:
            raise OperationActionError("AA_SHARE_NOT_FOUND")
        row = await self._owned(share.request_id, user_id, issuer=not reject)
        if reject and share.user_id != user_id:
            raise OperationActionError("AA_SHARE_NOT_FOUND")
        await acquire_security_user_lock(self.session, share.user_id)
        if share.workflow_id:
            await self.session.get(WorkflowModel, share.workflow_id, with_for_update=True)
        row = await self._owned(share.request_id, user_id, issuer=not reject, lock=True)
        self._version(row, expected_version)
        share = await self.session.get(
            AAShareModel, share_id, with_for_update=True, populate_existing=True
        )
        if share.operation_id or share.status != "PENDING":
            raise OperationActionError("AA_SHARE_SUBMITTED_OR_CLOSED_QUERY_ORIGINAL_OPERATION")
        share.status = "REJECTED" if reject else "CANCELLED"
        if share.workflow_id:
            workflow = await self.session.get(WorkflowModel, share.workflow_id)
            workflow.status, workflow.version = WorkflowStatus.CANCELLED, workflow.version + 1
        row.version += 1
        await self._event(row, "aa.share." + share.status.lower(), share)
        await self.session.commit()
        return await self.resource(row, user_id)

    async def list(self, user_id):
        rows = (
            await self.session.scalars(
                select(AARequestModel)
                .where(
                    ((AARequestModel.user_id == user_id) & AARequestModel.deleted_at.is_(None))
                    | (
                        (AARequestModel.user_id != user_id)
                        & AARequestModel.request_id.in_(
                            select(AAShareModel.request_id).where(AAShareModel.user_id == user_id)
                        )
                    )
                )
                .order_by(AARequestModel.created_at.desc())
            )
        ).all()
        return [await self.resource(row, user_id) for row in rows]

    async def get(self, request_id, user_id):
        return await self.resource(await self._owned(request_id, user_id), user_id)

    async def _can_delete(self, row, shares):
        others = [share for share in shares if share.user_id != row.user_id]
        if (
            row.deleted_at is not None
            or not row.snapshot_json
            or not others
            or any(
                share.operation_id
                or share.status != ("SELF_PAID" if share.user_id == row.user_id else "CANCELLED")
                for share in shares
            )
        ):
            return False
        # Keep submitted evidence even if a stale/legacy share missed its Operation link.
        operation = await self.session.scalar(
            select(OperationModel.operation_id)
            .where(
                OperationModel.workflow_id.in_(
                    [share.workflow_id for share in shares if share.workflow_id]
                )
            )
            .limit(1)
        )
        return operation is None

    async def delete_cancelled(self, request_id, user_id, expected_version):
        row = await self._owned(request_id, user_id, issuer=True, lock=True)
        self._version(row, expected_version)
        shares = (
            await self.session.scalars(
                select(AAShareModel)
                .where(AAShareModel.request_id == row.request_id)
                .execution_options(populate_existing=True)
            )
        ).all()
        # CANCELLED shares cannot become payable again; the request lock serializes
        # this check with close_share, without reversing payment's share lock order.
        if not await self._can_delete(row, shares):
            raise OperationActionError("ONLY_FULLY_CANCELLED_AA_CAN_BE_DELETED")
        row.deleted_at = _as_utc(self.clock())
        row.version += 1
        await self._event(row, "aa.deleted_from_list")
        await self.session.commit()

    async def resource(self, row, user_id):
        result = {
            "request_id": str(row.request_id),
            "conversation_id": str(row.conversation_id),
            "created_at": _as_utc(row.created_at).isoformat(),
            "version": row.version,
            "status": row.status,
            "is_initiator": row.user_id == user_id,
            "deadline": _as_utc(row.deadline).isoformat() if row.deadline else None,
            "snapshot": row.snapshot_json,
            "draft": row.draft_json if row.user_id == user_id else None,
            "payload_hash": row.payload_hash,
            "mock": True,
            "deleted_from_list": row.user_id == user_id and row.deleted_at is not None,
            "can_delete": False,
        }
        if row.status == "DRAFT":
            try:
                result["preview"] = self.preview(row)
            except OperationActionError as exc:
                result["required_input"] = str(exc)
            return result
        shares = (
            await self.session.scalars(
                select(AAShareModel)
                .where(AAShareModel.request_id == row.request_id)
                .order_by(AAShareModel.position)
            )
        ).all()
        rendered, received, self_paid, receivable = [], 0, 0, 0
        terminal = False
        for share in shares:
            status = share.status
            if share.operation_id:
                op = await self.session.get(OperationModel, share.operation_id)
                status = {
                    OperationStatus.SUCCEEDED: "PAID",
                    OperationStatus.FAILED: "FAILED",
                    OperationStatus.UNKNOWN: "UNKNOWN",
                }.get(op.status, "PROCESSING")
            elif status == "PENDING" and _as_utc(row.deadline) <= _as_utc(self.clock()):
                status = "EXPIRED"
            if status == "SELF_PAID":
                self_paid += share.amount_cents
            else:
                receivable += share.amount_cents
            if status == "PAID":
                received += share.amount_cents
            if status in {"CANCELLED", "REJECTED", "EXPIRED", "FAILED"}:
                terminal = True
            rendered.append(
                {
                    "share_id": str(share.share_id),
                    "display_name": share.display_name,
                    "amount": money(share.amount_cents),
                    "status": status,
                    "is_mine": share.user_id == user_id,
                    "workflow_id": str(share.workflow_id)
                    if share.workflow_id and share.user_id == user_id
                    else None,
                    "operation_id": str(share.operation_id)
                    if share.operation_id and share.user_id == user_id
                    else None,
                }
            )
        fully_cancelled = (
            bool(rendered)
            and any(s["status"] == "CANCELLED" for s in rendered)
            and all(s["status"] in {"CANCELLED", "SELF_PAID"} for s in rendered)
        )
        result.update(
            shares=rendered,
            receivable=money(receivable),
            received=money(received),
            outstanding=money(receivable - received),
            self_paid=money(self_paid),
            can_delete=row.user_id == user_id and await self._can_delete(row, shares),
            status="CANCELLED"
            if fully_cancelled
            else "COLLECTED"
            if received == receivable
            else "PARTIAL_CLOSED"
            if terminal
            else "PARTIAL"
            if received
            else "PUBLISHED",
        )
        return result

    async def _event(self, row, event_type, share=None):
        await EventPublisher(self.session).persist(
            event_type=event_type,
            conversation_id=row.conversation_id,
            task_id=row.source_task_id,
            data={
                "aa_request_id": str(row.request_id),
                "aa_share_id": str(share.share_id) if share else None,
                "workflow_id": str(share.workflow_id) if share and share.workflow_id else None,
                "operation_id": str(share.operation_id) if share and share.operation_id else None,
                "version": row.version,
                "payload_hash": row.payload_hash,
                "status": share.status if share else row.status,
            },
        )
