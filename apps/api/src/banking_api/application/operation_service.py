from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.domain.enums import (
    ApprovalStatus,
    OperationStatus,
    ReauthenticationStatus,
    WorkflowStatus,
)
from banking_api.domain.operation import OperationResource
from banking_api.persistence.models import OperationModel, WorkflowModel
from banking_api.persistence.repositories.approvals import ApprovalRepository
from banking_api.persistence.repositories.operations import OperationRepository
from banking_api.persistence.repositories.reauthentications import (
    ReauthenticationRepository,
)
from banking_api.persistence.repositories.workflows import WorkflowRepository
from banking_api.runtime.event_bus import EventBus
from banking_api.runtime.event_publisher import EventPublisher
from banking_api.workflows.transfer.authorization import (
    canonicalize_transfer_payload,
    transfer_payload_hash,
)
from banking_api.workflows.transfer.engine import (
    TransferWorkflowEngine,
    TransferWorkflowEngineError,
)
from banking_api.workflows.transfer.models import TransferWorkflowState


class OperationNotFoundError(Exception):
    pass


class OperationVersionConflictError(Exception):
    pass


class OperationActionError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class OperationService:
    """TRANSFER-only operation preparation, submission, and reconciliation."""

    def __init__(
        self,
        session: AsyncSession,
        bus: EventBus,
        engine: TransferWorkflowEngine,
        *,
        clock=_now,  # type: ignore[no-untyped-def]
    ) -> None:
        self.session = session
        self.bus = bus
        self.engine = engine
        self.clock = clock
        self.workflows = WorkflowRepository(session)
        self.approvals = ApprovalRepository(session)
        self.reauthentications = ReauthenticationRepository(session)
        self.operations = OperationRepository(session)
        self.publisher = EventPublisher(session, bus)

    async def get(self, operation_id: UUID, *, user_id: str) -> OperationResource:
        model = await self.operations.get_for_user(operation_id, user_id)
        if model is None:
            raise OperationNotFoundError
        return self._resource(model)

    async def commit_workflow(
        self, workflow_id: UUID, *, user_id: str, expected_version: int
    ) -> OperationResource:
        operation = await self.prepare_transfer(
            workflow_id, user_id=user_id, expected_version=expected_version
        )
        return await self.reconcile(
            operation.operation_id,
            user_id=user_id,
            expected_version=operation.version,
        )

    async def prepare_transfer(
        self, workflow_id: UUID, *, user_id: str, expected_version: int
    ) -> OperationResource:
        workflow = await self.workflows.get_for_user_for_update(workflow_id, user_id)
        if workflow is None:
            raise OperationNotFoundError
        if workflow.version != expected_version:
            raise OperationVersionConflictError
        if workflow.status is not WorkflowStatus.READY_FOR_COMMIT:
            raise OperationActionError("WORKFLOW_NOT_READY_FOR_COMMIT")
        if await self.operations.get_for_workflow(workflow_id, user_id) is not None:
            raise OperationActionError("TRANSFER_OPERATION_ALREADY_EXISTS")

        state = TransferWorkflowState.model_validate(workflow.state_json)
        authorization = state.authorization
        if authorization is None or state.review_payload is None:
            raise OperationActionError("TRANSFER_AUTHORIZATION_MISSING")
        approval = await self.approvals.get_for_workflow_user_for_update(
            authorization.approval_id, workflow_id, user_id
        )
        if approval is None:
            raise OperationActionError("APPROVAL_NOT_FOUND")
        now = _as_utc(self.clock())
        if approval.status is not ApprovalStatus.APPROVED or approval.consumed_at is not None:
            raise OperationActionError("APPROVAL_NOT_CONSUMABLE")
        if _as_utc(approval.expires_at) <= now:
            await self._expire_approval(workflow, state, approval)
            raise OperationActionError("APPROVAL_EXPIRED")
        if authorization.reauth_id is None:
            raise OperationActionError("REAUTH_NOT_FOUND")
        reauth = await self.reauthentications.get_for_workflow_user_for_update(
            authorization.reauth_id, workflow_id, user_id
        )
        if reauth is None or reauth.approval_id != approval.approval_id:
            raise OperationActionError("REAUTH_APPROVAL_MISMATCH")
        if reauth.status is not ReauthenticationStatus.VERIFIED:
            raise OperationActionError("REAUTH_NOT_VERIFIED")
        if _as_utc(reauth.expires_at) <= now:
            await self._expire_reauthentication(workflow, state, reauth)
            raise OperationActionError("REAUTH_EXPIRED")

        initial_hash = transfer_payload_hash(state.review_payload)
        if (
            initial_hash != approval.payload_hash
            or initial_hash != authorization.approval_payload_hash
        ):
            raise OperationActionError("APPROVAL_PAYLOAD_MISMATCH")
        try:
            self.engine.ensure_commit_allowed()
        except TransferWorkflowEngineError as exc:
            raise OperationActionError("TRANSFER_COMMIT_POLICY_DENIED") from exc

        try:
            validation_status, state = await self.engine.advance(state)
        except TransferWorkflowEngineError as exc:
            raise OperationActionError("FINAL_VALIDATION_UNAVAILABLE") from exc
        if validation_status is not WorkflowStatus.READY_FOR_REVIEW or state.review_payload is None:
            await self._fail_final_validation(workflow, state)
            raise OperationActionError("FINAL_TRANSFER_VALIDATION_FAILED")
        current_hash = transfer_payload_hash(state.review_payload)
        if current_hash != approval.payload_hash:
            raise OperationActionError("APPROVAL_PAYLOAD_MISMATCH")

        operation = await self.operations.create_transfer(
            user_id=user_id,
            workflow_id=workflow_id,
            approval_id=approval.approval_id,
            payload=canonicalize_transfer_payload(state.review_payload),
            payload_hash=current_hash,
            idempotency_key=uuid4(),
        )
        approval.status = ApprovalStatus.CONSUMED
        approval.consumed_at = now
        approval.consumed_by_operation_id = operation.operation_id
        updated = await self.workflows.update_if_version(
            workflow_id=workflow_id,
            user_id=user_id,
            expected_version=expected_version,
            status=WorkflowStatus.COMMITTING,
            state=state.model_dump(mode="json"),
        )
        if updated is None:
            await self.session.rollback()
            raise OperationVersionConflictError
        created = await self._operation_event(operation, "operation.created")
        committing = await self.publisher.persist(
            event_type="workflow.committing",
            conversation_id=workflow.conversation_id,
            task_id=workflow.source_task_id,
            data=self._workflow_event_data(updated),
        )
        await self.session.commit()
        await self.publisher.publish_persisted(created, committing)
        return self._resource(operation)

    async def reconcile(
        self, operation_id: UUID, *, user_id: str, expected_version: int
    ) -> OperationResource:
        operation = await self.operations.get_for_user(operation_id, user_id)
        if operation is None:
            raise OperationNotFoundError
        if operation.version != expected_version:
            raise OperationVersionConflictError
        if operation.status in {OperationStatus.SUCCEEDED, OperationStatus.FAILED}:
            return self._resource(operation)

        if operation.status is OperationStatus.CREATED:
            operation = await self._submit_created(operation)
            if operation.status is not OperationStatus.SUBMITTED:
                return self._resource(operation)
        return await self._query_status(operation)

    async def _submit_created(self, operation: OperationModel) -> OperationModel:
        now = _as_utc(self.clock())
        try:
            output = await self.engine.submit_operation(operation.operation_id)
        except TransferWorkflowEngineError:
            output = {"outcome": "UNKNOWN", "error_code": "SUBMISSION_AMBIGUOUS"}
        outcome = output["outcome"]
        if outcome == "ACCEPTED":
            status = OperationStatus.SUBMITTED
            submitted_at = now
            completed_at = None
            event_type = "operation.submitted"
        elif outcome == "FAILED":
            status = OperationStatus.FAILED
            submitted_at = None
            completed_at = now
            event_type = "operation.failed"
        else:
            status = OperationStatus.UNKNOWN
            submitted_at = None
            completed_at = None
            event_type = "operation.unknown"
        return await self._transition(
            operation,
            status=status,
            provider_reference=output.get("provider_reference"),
            error_code=output.get("error_code"),
            error_message=output.get("error_message"),
            submitted_at=submitted_at,
            completed_at=completed_at,
            event_type=event_type,
        )

    async def _query_status(self, operation: OperationModel) -> OperationResource:
        try:
            output = await self.engine.query_operation_status(operation.operation_id)
        except TransferWorkflowEngineError:
            output = {"status": "UNKNOWN", "error_code": "STATUS_UNAVAILABLE"}
        provider_status = output["status"]
        now = _as_utc(self.clock())
        if provider_status == "SUCCEEDED":
            status = OperationStatus.SUCCEEDED
            completed_at = now
            event_type = "operation.succeeded"
        elif provider_status == "FAILED":
            status = OperationStatus.FAILED
            completed_at = now
            event_type = "operation.failed"
        elif provider_status == "PENDING":
            status = OperationStatus.SUBMITTED
            completed_at = None
            event_type = "operation.submitted"
        else:
            status = OperationStatus.UNKNOWN
            completed_at = None
            event_type = "operation.unknown"
        updated = await self._transition(
            operation,
            status=status,
            provider_reference=output.get("provider_reference") or operation.provider_reference,
            error_code=output.get("error_code"),
            error_message=output.get("error_message"),
            submitted_at=operation.submitted_at,
            completed_at=completed_at,
            event_type=event_type,
        )
        return self._resource(updated)

    async def _transition(
        self,
        operation: OperationModel,
        *,
        status: OperationStatus,
        provider_reference: str | None,
        error_code: str | None,
        error_message: str | None,
        submitted_at: datetime | None,
        completed_at: datetime | None,
        event_type: str,
    ) -> OperationModel:
        workflow = await self.workflows.get_for_user_for_update(
            operation.workflow_id, operation.user_id
        )
        if workflow is None:
            raise OperationNotFoundError
        updated_operation = await self.operations.update_if_version(
            operation_id=operation.operation_id,
            user_id=operation.user_id,
            expected_version=operation.version,
            status=status,
            provider_reference=provider_reference,
            error_code=error_code,
            error_message=error_message,
            submitted_at=submitted_at,
            completed_at=completed_at,
        )
        if updated_operation is None:
            await self.session.rollback()
            raise OperationVersionConflictError
        workflow_status = (
            WorkflowStatus.SUCCEEDED
            if status is OperationStatus.SUCCEEDED
            else WorkflowStatus.FAILED
            if status is OperationStatus.FAILED
            else WorkflowStatus.COMMITTING
        )
        updated_workflow = await self.workflows.update_if_version(
            workflow_id=workflow.workflow_id,
            user_id=workflow.user_id,
            expected_version=workflow.version,
            status=workflow_status,
            state=workflow.state_json,
        )
        if updated_workflow is None:
            await self.session.rollback()
            raise OperationVersionConflictError
        operation_event = await self._operation_event(updated_operation, event_type)
        workflow_event_type = {
            WorkflowStatus.SUCCEEDED: "workflow.succeeded",
            WorkflowStatus.FAILED: "workflow.failed",
        }.get(workflow_status, "workflow.committing")
        workflow_event = await self.publisher.persist(
            event_type=workflow_event_type,
            conversation_id=workflow.conversation_id,
            task_id=workflow.source_task_id,
            data=self._workflow_event_data(updated_workflow),
        )
        await self.session.commit()
        await self.publisher.publish_persisted(operation_event, workflow_event)
        return updated_operation

    async def _expire_approval(self, workflow, state, approval) -> None:  # type: ignore[no-untyped-def]
        approval.status = ApprovalStatus.EXPIRED
        resource_events: list[tuple[str, dict[str, object]]] = [
            (
                "approval.expired",
                {
                    "workflow_id": str(workflow.workflow_id),
                    "approval_id": str(approval.approval_id),
                    "status": approval.status.value,
                    "expires_at": approval.expires_at.isoformat(),
                },
            )
        ]
        if state.authorization is not None and state.authorization.reauth_id is not None:
            reauth = await self.reauthentications.get_for_workflow_user_for_update(
                state.authorization.reauth_id, workflow.workflow_id, workflow.user_id
            )
            if reauth is not None and reauth.status in {
                ReauthenticationStatus.PENDING,
                ReauthenticationStatus.VERIFIED,
            }:
                reauth.status = ReauthenticationStatus.INVALIDATED
                resource_events.append(
                    (
                        "reauth.invalidated",
                        {
                            "workflow_id": str(workflow.workflow_id),
                            "reauth_id": str(reauth.reauth_id),
                            "status": reauth.status.value,
                        },
                    )
                )
        state.authorization = None
        await self._persist_safe_workflow_transition(
            workflow,
            state,
            WorkflowStatus.READY_FOR_REVIEW,
            "workflow.ready_for_review",
            resource_events=resource_events,
        )

    async def _expire_reauthentication(self, workflow, state, reauth) -> None:  # type: ignore[no-untyped-def]
        reauth.status = ReauthenticationStatus.EXPIRED
        assert state.authorization is not None
        state.authorization.reauth_id = None
        state.authorization.reauth_verified_at = None
        state.authorization.reauth_expires_at = None
        await self._persist_safe_workflow_transition(
            workflow,
            state,
            WorkflowStatus.REAUTH_REQUIRED,
            "workflow.reauth_required",
            resource_events=[
                (
                    "reauth.expired",
                    {
                        "workflow_id": str(workflow.workflow_id),
                        "reauth_id": str(reauth.reauth_id),
                        "status": reauth.status.value,
                        "expires_at": reauth.expires_at.isoformat(),
                    },
                )
            ],
        )

    async def _fail_final_validation(
        self, workflow: WorkflowModel, state: TransferWorkflowState
    ) -> None:
        await self._persist_safe_workflow_transition(
            workflow, state, WorkflowStatus.FAILED, "workflow.failed"
        )

    async def _persist_safe_workflow_transition(
        self,
        workflow: WorkflowModel,
        state: TransferWorkflowState,
        status: WorkflowStatus,
        event_type: str,
        *,
        resource_events: list[tuple[str, dict[str, object]]] | None = None,
    ) -> None:
        updated = await self.workflows.update_if_version(
            workflow_id=workflow.workflow_id,
            user_id=workflow.user_id,
            expected_version=workflow.version,
            status=status,
            state=state.model_dump(mode="json"),
        )
        if updated is None:
            await self.session.rollback()
            raise OperationVersionConflictError
        events = [
            await self.publisher.persist(
                event_type=resource_event_type,
                conversation_id=workflow.conversation_id,
                task_id=workflow.source_task_id,
                data=data,
            )
            for resource_event_type, data in (resource_events or [])
        ]
        events.append(
            await self.publisher.persist(
                event_type=event_type,
                conversation_id=workflow.conversation_id,
                task_id=workflow.source_task_id,
                data=self._workflow_event_data(updated),
            )
        )
        await self.session.commit()
        await self.publisher.publish_persisted(*events)

    async def _operation_event(self, operation: OperationModel, event_type: str):  # type: ignore[no-untyped-def]
        workflow = await self.workflows.get_for_user(operation.workflow_id, operation.user_id)
        if workflow is None:
            raise OperationNotFoundError
        data: dict[str, object] = {
            "operation_id": str(operation.operation_id),
            "workflow_id": str(operation.workflow_id),
            "operation_type": operation.operation_type.value,
            "status": operation.status.value,
            "version": operation.version,
        }
        if operation.provider_reference is not None:
            data["provider_reference"] = operation.provider_reference
        if operation.error_code is not None:
            data["error_code"] = operation.error_code
        return await self.publisher.persist(
            event_type=event_type,
            conversation_id=workflow.conversation_id,
            task_id=workflow.source_task_id,
            data=data,
        )

    @staticmethod
    def _workflow_event_data(model: WorkflowModel) -> dict[str, object]:
        return {
            "workflow_id": str(model.workflow_id),
            "workflow_type": model.workflow_type.value,
            "status": model.status.value,
            "version": model.version,
        }

    @staticmethod
    def _resource(model: OperationModel) -> OperationResource:
        return OperationResource(
            operation_id=model.operation_id,
            workflow_id=model.workflow_id,
            operation_type=model.operation_type,
            status=model.status,
            version=model.version,
            provider_reference=model.provider_reference,
            error_code=model.error_code,
            error_message=model.error_message,
            created_at=model.created_at,
            submitted_at=model.submitted_at,
            completed_at=model.completed_at,
            updated_at=model.updated_at,
        )
