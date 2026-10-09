"""Revocable, one-use Mock appointment authority. No reusable OTP is persisted."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

from banking_api.application.operation_service import OperationActionError, _as_utc
from banking_api.config.settings import get_settings
from banking_api.domain.enums import ApprovalStatus, ReauthenticationStatus, WorkflowStatus
from banking_api.persistence.models import (
    ApprovalModel,
    OperationModel,
    ReauthenticationModel,
    RecurringTransferModel,
    ScheduledAuthorizationModel,
    ScheduledTransferModel,
    TaskModel,
    WorkflowModel,
)
from banking_api.runtime.event_publisher import EventPublisher
from banking_api.security.guard import SecurityGuardService, acquire_security_user_lock
from banking_api.workflows.transfer.authorization import (
    canonicalize_transfer_payload,
    transfer_payload_hash,
)
from banking_api.workflows.transfer.models import MonthlyRecurrence, TransferWorkflowState


def require_mock_scheduling(engine) -> None:
    if not get_settings().mock_scheduled_transfers_enabled or not getattr(
        engine, "mock_scheduling_supported", False
    ):
        raise OperationActionError("MOCK_SCHEDULING_DISABLED")


class ScheduleAction(BaseModel):
    expected_version: int


class ScheduledTransfer(BaseModel):
    schedule_id: UUID
    workflow_id: UUID
    version: int
    status: str
    scheduled_for: datetime | None
    execute_deadline: datetime | None
    business_timezone: str
    operation_id: UUID | None
    error_code: str | None
    series_id: UUID | None = None
    occurrence_index: int | None = None
    series_version: int | None = None
    series_revoked: bool = False
    recurrence: MonthlyRecurrence | None = None
    task_title: str = "转账任务"
    remark: str = ""
    created_at: datetime | None = None
    mock: bool = True


class ScheduleService:
    def __init__(self, session, engine, *, clock=lambda: datetime.now(UTC)):
        self.session, self.engine, self.clock = session, engine, clock

    async def list(self, user_id: str) -> list[ScheduledTransfer]:
        rows = (
            await self.session.scalars(
                select(ScheduledTransferModel)
                .where(
                    ScheduledTransferModel.user_id == user_id,
                    ScheduledTransferModel.deleted_at.is_(None),
                )
                .order_by(ScheduledTransferModel.scheduled_for.desc())
            )
        ).all()
        return [await self.resource(row) for row in rows]

    async def get(self, schedule_id: UUID, user_id: str) -> ScheduledTransfer:
        return await self.resource(await self._owned(schedule_id, user_id))

    async def _owned(self, schedule_id, user_id, *, lock=False):
        row = await self.session.get(ScheduledTransferModel, schedule_id)
        if row is None or row.user_id != user_id:
            raise OperationActionError("SCHEDULE_NOT_FOUND")
        if lock:
            # Every mutation uses Security -> Workflow -> Schedule, including the Worker.
            await acquire_security_user_lock(self.session, user_id)
            await self.session.get(WorkflowModel, row.workflow_id, with_for_update=True)
            row = await self.session.get(
                ScheduledTransferModel, schedule_id, with_for_update=True, populate_existing=True
            )
        return row

    async def resource(self, row) -> ScheduledTransfer:
        status, error = row.status, row.error_code
        if row.operation_id:
            op = await self.session.get(OperationModel, row.operation_id)
            status = {"SUCCEEDED": "SUCCEEDED", "FAILED": "FAILED", "UNKNOWN": "UNKNOWN"}.get(
                op.status.value, "EXECUTING"
            )
            error = op.error_code
        series = (
            await self.session.get(RecurringTransferModel, row.series_id) if row.series_id else None
        )
        workflow = await self.session.get(WorkflowModel, row.workflow_id)
        state = TransferWorkflowState.model_validate(workflow.state_json)
        review = state.review_payload
        recipient = (
            review.payee_display_name if review else state.draft.recipient_query or "待确认收款人"
        )
        amount = review.amount if review else state.draft.amount
        title = f"给{recipient}转账" + (
            f" ¥{amount:.2f}" if amount is not None else "（金额待补充）"
        )
        return ScheduledTransfer(
            task_title=title,
            remark=review.remark if review else state.draft.remark,
            created_at=workflow.created_at,
            schedule_id=row.schedule_id,
            workflow_id=row.workflow_id,
            version=row.version,
            status=status,
            scheduled_for=row.scheduled_for,
            execute_deadline=row.execute_deadline,
            business_timezone=row.business_timezone,
            operation_id=row.operation_id,
            error_code=error,
            series_id=row.series_id,
            occurrence_index=row.occurrence_index,
            series_version=series.version if series else None,
            series_revoked=bool(series and series.revoked_at),
            recurrence=__import__("json").loads(series.scope_json["recurrence"])
            if series
            else None,
        )

    async def authorize(self, schedule_id: UUID, user_id: str, expected_version: int):
        require_mock_scheduling(self.engine)
        row = await self._owned(schedule_id, user_id, lock=True)
        await SecurityGuardService(self.session, clock=self.clock).require_write_allowed(user_id)
        workflow = await self.session.get(WorkflowModel, row.workflow_id)
        if workflow.version != expected_version:
            raise OperationActionError("WORKFLOW_VERSION_CONFLICT")
        if row.status != "PENDING_AUTHORIZATION" or row.operation_id:
            raise OperationActionError("SCHEDULE_NOT_AUTHORIZABLE")
        state = TransferWorkflowState.model_validate(workflow.state_json)
        now = _as_utc(self.clock())
        if (
            workflow.status != WorkflowStatus.READY_FOR_COMMIT
            or state.authorization is None
            or state.review_payload is None
        ):
            raise OperationActionError("SCHEDULE_STRONG_VERIFICATION_REQUIRED")
        if row.scheduled_for is None or _as_utc(row.scheduled_for) <= now:
            raise OperationActionError("SCHEDULE_TIME_TOO_SOON")
        approval = await self.session.get(
            ApprovalModel, state.authorization.approval_id, with_for_update=True
        )
        reauth = (
            await self.session.get(
                ReauthenticationModel, state.authorization.reauth_id, with_for_update=True
            )
            if state.authorization.reauth_id
            else None
        )
        payload = canonicalize_transfer_payload(state.review_payload)
        digest = transfer_payload_hash(state.review_payload)
        if (
            approval is None
            or approval.user_id != user_id
            or approval.workflow_id != workflow.workflow_id
            or approval.status != ApprovalStatus.APPROVED
            or approval.consumed_at is not None
            or _as_utc(approval.expires_at) <= now
            or approval.payload_hash != digest
            or state.authorization.approval_payload_hash != digest
        ):
            raise OperationActionError("SCHEDULE_APPROVAL_INVALID")
        if (
            reauth is None
            or reauth.user_id != user_id
            or reauth.workflow_id != workflow.workflow_id
            or reauth.approval_id != approval.approval_id
            or reauth.status != ReauthenticationStatus.VERIFIED
            or _as_utc(reauth.expires_at) <= now
        ):
            raise OperationActionError("SCHEDULE_STRONG_VERIFICATION_REQUIRED")
        grant = ScheduledAuthorizationModel(
            schedule_id=row.schedule_id,
            user_id=user_id,
            workflow_id=workflow.workflow_id,
            approval_id=approval.approval_id,
            reauth_id=reauth.reauth_id,
            payload_hash=digest,
            payload_json=payload,
            authorized_at=now,
        )
        self.session.add(grant)
        await self.session.flush()
        row.authorization_id, row.status = grant.authorization_id, "SCHEDULED"
        row.version += 1
        # Convert the instant approval; the persisted scoped grant authorizes only this appointment.
        approval.status, approval.consumed_at = ApprovalStatus.CONSUMED, now
        if state.review_payload.recurrence:
            await self._materialize_series(row, workflow, state, approval, reauth, now)
        await self._event(row, "schedule.authorized")
        await self.session.commit()
        return await self.resource(row)

    async def _materialize_series(self, row, workflow, state, approval, reauth, now):
        from banking_api.domain.enums import TaskStatus

        recurrence = state.review_payload.recurrence
        if any(_as_utc(when) <= now for when in recurrence.occurrences):
            raise OperationActionError("SCHEDULE_TIME_TOO_SOON")
        series = RecurringTransferModel(
            user_id=row.user_id,
            root_workflow_id=workflow.workflow_id,
            approval_id=approval.approval_id,
            reauth_id=reauth.reauth_id,
            scope_json=canonicalize_transfer_payload(state.review_payload),
            scope_hash=transfer_payload_hash(state.review_payload),
            authorized_at=now,
        )
        self.session.add(series)
        await self.session.flush()
        row.series_id, row.occurrence_index = series.series_id, 1
        window = _as_utc(row.execute_deadline) - _as_utc(row.scheduled_for)
        for index, when in enumerate(recurrence.occurrences[1:], 2):
            child_state = state.model_copy(deep=True)
            child_state.draft.scheduled_for = child_state.review_payload.scheduled_for = when
            child_state.draft.execute_deadline = child_state.review_payload.execute_deadline = (
                when + window
            )
            # This is a derived occurrence, never a new model request or a new user verification.
            task = TaskModel(
                user_id=row.user_id,
                conversation_id=workflow.conversation_id,
                task_type="recurring_transfer_occurrence",
                status=TaskStatus.COMPLETED,
                input_json={"series_id": str(series.series_id), "occurrence_index": index},
                next_run_at=None,
            )
            self.session.add(task)
            await self.session.flush()
            child = WorkflowModel(
                user_id=row.user_id,
                conversation_id=workflow.conversation_id,
                source_task_id=task.task_id,
                workflow_type=workflow.workflow_type,
                status=WorkflowStatus.READY_FOR_COMMIT,
                state_json={},
            )
            self.session.add(child)
            await self.session.flush()
            child_schedule = ScheduledTransferModel(
                user_id=row.user_id,
                workflow_id=child.workflow_id,
                series_id=series.series_id,
                occurrence_index=index,
                status="SCHEDULED",
                scheduled_for=when,
                execute_deadline=when + window,
                business_timezone=row.business_timezone,
            )
            self.session.add(child_schedule)
            await self.session.flush()
            child_state.draft.schedule_id = child_schedule.schedule_id
            digest = transfer_payload_hash(child_state.review_payload)
            # Consumed evidence cannot authorize an instant transfer. Its authority comes solely
            # from the immutable series scope and the one-use scheduled grant below.
            evidence = ApprovalModel(
                user_id=row.user_id,
                workflow_id=child.workflow_id,
                approval_type=approval.approval_type,
                payload_json=canonicalize_transfer_payload(child_state.review_payload),
                payload_hash=digest,
                status=ApprovalStatus.CONSUMED,
                expires_at=approval.expires_at,
                approved_at=approval.approved_at,
                consumed_at=now,
            )
            self.session.add(evidence)
            await self.session.flush()
            child_state.authorization.approval_id = evidence.approval_id
            child_state.authorization.approval_payload_hash = digest
            child.state_json = child_state.model_dump(mode="json")
            grant = ScheduledAuthorizationModel(
                schedule_id=child_schedule.schedule_id,
                user_id=row.user_id,
                workflow_id=child.workflow_id,
                approval_id=evidence.approval_id,
                reauth_id=reauth.reauth_id,
                payload_json=evidence.payload_json,
                payload_hash=digest,
                authorized_at=now,
            )
            self.session.add(grant)
            await self.session.flush()
            child_schedule.authorization_id = grant.authorization_id
            task.output_json = {
                "workflow_id": str(child.workflow_id),
                "series_id": str(series.series_id),
            }
            await self._event(child_schedule, "schedule.occurrence.authorized")
        await self._event(row, "schedule.series.authorized")

    async def cancel_series(self, schedule_id, user_id, expected_version):
        row = await self._owned(schedule_id, user_id, lock=True)
        if row.series_id is None:
            raise OperationActionError("RECURRING_SERIES_NOT_FOUND")
        series = await self.session.get(RecurringTransferModel, row.series_id, with_for_update=True)
        if series.user_id != user_id or series.version != expected_version:
            raise OperationActionError("RECURRING_SERIES_VERSION_CONFLICT")
        if series.revoked_at:
            raise OperationActionError("RECURRING_SERIES_ALREADY_REVOKED")
        series.revoked_at = _as_utc(self.clock())
        series.version += 1
        # The per-user security lock serializes this transaction against all preparations.
        siblings = (
            await self.session.scalars(
                select(ScheduledTransferModel)
                .where(ScheduledTransferModel.series_id == series.series_id)
                .order_by(ScheduledTransferModel.occurrence_index)
            )
        ).all()
        for item in siblings:
            if item.operation_id or item.status not in {"SCHEDULED", "EXECUTING"}:
                continue
            wf = await self.session.get(WorkflowModel, item.workflow_id, with_for_update=True)
            item = await self.session.get(
                ScheduledTransferModel,
                item.schedule_id,
                with_for_update=True,
                populate_existing=True,
            )
            grant = await self.session.get(ScheduledAuthorizationModel, item.authorization_id)
            grant.revoked_at = series.revoked_at
            item.status, item.lease_owner, item.lease_expires_at = "CANCELLED", None, None
            item.version += 1
            wf.status, wf.version = WorkflowStatus.CANCELLED, wf.version + 1
            await self._event(item, "schedule.cancelled")
        await self._event(row, "schedule.series.revoked")
        await self.session.commit()
        return await self.resource(row)

    async def delete_cancelled(self, schedule_id, user_id, expected_version):
        row = await self._owned(schedule_id, user_id, lock=True)
        if row.version != expected_version:
            raise OperationActionError("SCHEDULE_VERSION_CONFLICT")
        items = [row]
        if row.series_id:
            items = list(
                (
                    await self.session.scalars(
                        select(ScheduledTransferModel)
                        .where(ScheduledTransferModel.series_id == row.series_id)
                        .order_by(ScheduledTransferModel.occurrence_index)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                ).all()
            )
        if any(
            item.user_id != user_id or item.status != "CANCELLED" or item.operation_id
            for item in items
        ):
            raise OperationActionError("ONLY_CANCELLED_SCHEDULE_TASK_CAN_BE_DELETED")
        for item in items:
            if item.deleted_at is None:
                item.deleted_at = _as_utc(self.clock())
                item.version += 1
                await self._event(item, "schedule.deleted_from_list")
        await self.session.commit()
        return await self.resource(row)

    async def cancel(self, schedule_id: UUID, user_id: str, expected_version: int):
        row = await self._owned(schedule_id, user_id, lock=True)
        if row.version != expected_version:
            raise OperationActionError("SCHEDULE_VERSION_CONFLICT")
        if row.operation_id:
            raise OperationActionError("SCHEDULE_ALREADY_SUBMITTING_QUERY_OPERATION")
        if row.status not in {"PENDING_AUTHORIZATION", "SCHEDULED", "EXECUTING"}:
            raise OperationActionError("SCHEDULE_NOT_CANCELLABLE")
        if row.authorization_id:
            grant = await self.session.get(
                ScheduledAuthorizationModel, row.authorization_id, with_for_update=True
            )
            grant.revoked_at = _as_utc(self.clock())
        row.status, row.lease_owner, row.lease_expires_at = "CANCELLED", None, None
        row.version += 1
        workflow = await self.session.get(WorkflowModel, row.workflow_id)
        workflow.status, workflow.version = WorkflowStatus.CANCELLED, workflow.version + 1
        await self._event(row, "schedule.cancelled")
        await self.session.commit()
        return await self.resource(row)

    async def _event(self, row, event_type):
        workflow = await self.session.get(WorkflowModel, row.workflow_id)
        await EventPublisher(self.session).persist(
            event_type=event_type,
            conversation_id=workflow.conversation_id,
            task_id=workflow.source_task_id,
            data={
                "schedule_id": str(row.schedule_id),
                "series_id": str(row.series_id) if row.series_id else None,
                "occurrence_index": row.occurrence_index,
                "workflow_id": str(row.workflow_id),
                "status": row.status,
                "payload_hash": (
                    await self.session.get(ScheduledAuthorizationModel, row.authorization_id)
                ).payload_hash
                if row.authorization_id
                else None,
                "version": row.version,
                "mock": True,
            },
        )


async def validate_recurring_scope(session, scheduled, grant, user_id):
    """Validate each derived grant against the originally confirmed finite scope."""
    import hashlib
    import json

    series = await session.get(RecurringTransferModel, scheduled.series_id)
    if series is None or series.user_id != user_id or series.revoked_at is not None:
        raise OperationActionError("RECURRING_AUTHORIZATION_REVOKED")
    digest = hashlib.sha256(
        json.dumps(
            series.scope_json, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    approval = await session.get(ApprovalModel, series.approval_id)
    reauth = await session.get(ReauthenticationModel, series.reauth_id)
    if (
        digest != series.scope_hash
        or approval is None
        or approval.user_id != user_id
        or approval.workflow_id != series.root_workflow_id
        or approval.payload_hash != digest
        or approval.status != ApprovalStatus.CONSUMED
        or reauth is None
        or reauth.user_id != user_id
        or reauth.workflow_id != series.root_workflow_id
        or reauth.approval_id != approval.approval_id
        or reauth.status != ReauthenticationStatus.VERIFIED
        or grant.reauth_id != series.reauth_id
    ):
        raise OperationActionError("RECURRING_AUTHORIZATION_INVALID")
    rule = json.loads(series.scope_json["recurrence"])
    index = scheduled.occurrence_index
    dates = rule["occurrences"]
    if index is None or index < 1 or index > len(dates) or len(dates) != rule["count"]:
        raise OperationActionError("RECURRING_OCCURRENCE_INVALID")
    when = datetime.fromisoformat(dates[index - 1].replace("Z", "+00:00"))
    first = datetime.fromisoformat(series.scope_json["scheduled_for"])
    window = datetime.fromisoformat(series.scope_json["execute_deadline"]) - first
    expected = {
        **series.scope_json,
        "scheduled_for": when.astimezone(UTC).isoformat(),
        "execute_deadline": (when + window).astimezone(UTC).isoformat(),
    }
    if (
        expected != grant.payload_json
        or _as_utc(scheduled.scheduled_for) != when
        or _as_utc(scheduled.execute_deadline) != when + window
    ):
        raise OperationActionError("RECURRING_AUTHORIZATION_SCOPE_MISMATCH")
