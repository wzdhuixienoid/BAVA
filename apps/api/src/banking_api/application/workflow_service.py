from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.domain.enums import WorkflowStatus
from banking_api.domain.workflow import Workflow, WorkflowType
from banking_api.persistence.repositories.workflows import WorkflowRepository
from banking_api.runtime.event_bus import EventBus
from banking_api.runtime.event_publisher import EventPublisher
from banking_api.workflows.transfer.engine import (
    InvalidWorkflowActionError,
    TransferWorkflowEngine,
)
from banking_api.workflows.transfer.models import TransferIntent, TransferWorkflowState


class WorkflowNotFoundError(Exception):
    pass


class WorkflowVersionConflictError(Exception):
    pass


class WorkflowActionError(Exception):
    pass


def to_workflow(model) -> Workflow:  # type: ignore[no-untyped-def]
    return Workflow(
        workflow_id=model.workflow_id,
        user_id=model.user_id,
        conversation_id=model.conversation_id,
        source_task_id=model.source_task_id,
        workflow_type=model.workflow_type,
        status=model.status,
        version=model.version,
        state=model.state_json,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class WorkflowService:
    def __init__(
        self,
        session: AsyncSession,
        bus: EventBus,
        engine: TransferWorkflowEngine,
    ) -> None:
        self.session = session
        self.repository = WorkflowRepository(session)
        self.publisher = EventPublisher(session, bus)
        self.engine = engine

    async def get(self, workflow_id: UUID, *, user_id: str) -> Workflow:
        model = await self.repository.get_for_user(workflow_id, user_id)
        if model is None:
            raise WorkflowNotFoundError
        return to_workflow(model)

    async def list(
        self, *, user_id: str, conversation_id: UUID | None = None
    ) -> list[Workflow]:
        models = await self.repository.list_for_user(user_id, conversation_id)
        return [to_workflow(model) for model in models]

    async def create_transfer(
        self,
        *,
        user_id: str,
        conversation_id: UUID,
        source_task_id: UUID,
        intent: TransferIntent,
    ) -> Workflow:
        initial = TransferWorkflowState(draft=intent.model_dump())
        model = await self.repository.create(
            user_id=user_id,
            conversation_id=conversation_id,
            source_task_id=source_task_id,
            workflow_type=WorkflowType.TRANSFER,
            status=WorkflowStatus.DRAFT,
            state=initial.model_dump(mode="json"),
        )
        created = await self.publisher.persist(
            event_type="workflow.created",
            conversation_id=conversation_id,
            task_id=source_task_id,
            data=self._event_data(model),
        )
        status, state = await self.engine.advance(initial)
        updated = await self.repository.update_if_version(
            workflow_id=model.workflow_id,
            user_id=user_id,
            expected_version=model.version,
            status=status,
            state=state.model_dump(mode="json"),
        )
        if updated is None:
            raise WorkflowVersionConflictError
        state_event = await self.publisher.persist(
            event_type=self._event_type(status),
            conversation_id=conversation_id,
            task_id=source_task_id,
            data=self._event_data(updated),
        )
        await self.session.commit()
        await self.publisher.publish_persisted(created, state_event)
        return to_workflow(updated)

    async def select_payee(
        self, workflow_id: UUID, *, user_id: str, payee_id: str, expected_version: int
    ) -> Workflow:
        model, state = await self._load_action(workflow_id, user_id, expected_version)
        try:
            await self.engine.validate_payee_action(state, payee_id)
        except InvalidWorkflowActionError as exc:
            raise WorkflowActionError(str(exc)) from exc
        state.draft.payee_id = payee_id
        return await self._advance_and_save(model, state, expected_version)

    async def select_source_account(
        self, workflow_id: UUID, *, user_id: str, account_id: str, expected_version: int
    ) -> Workflow:
        model, state = await self._load_action(workflow_id, user_id, expected_version)
        try:
            await self.engine.validate_account_action(state, account_id)
        except InvalidWorkflowActionError as exc:
            raise WorkflowActionError(str(exc)) from exc
        state.draft.source_account_id = account_id
        return await self._advance_and_save(model, state, expected_version)

    async def set_amount(
        self, workflow_id: UUID, *, user_id: str, amount: Decimal, expected_version: int
    ) -> Workflow:
        model, state = await self._load_action(workflow_id, user_id, expected_version)
        if state.required_input is None or state.required_input.type.value != "AMOUNT":
            raise WorkflowActionError("Workflow is not waiting for an amount")
        state.draft.amount = amount
        return await self._advance_and_save(model, state, expected_version)

    async def cancel(
        self, workflow_id: UUID, *, user_id: str, expected_version: int
    ) -> Workflow:
        model, state = await self._load_action(workflow_id, user_id, expected_version)
        if model.status is WorkflowStatus.CANCELLED:
            raise WorkflowActionError("Workflow is already cancelled")
        updated = await self.repository.update_if_version(
            workflow_id=model.workflow_id,
            user_id=user_id,
            expected_version=expected_version,
            status=WorkflowStatus.CANCELLED,
            state=state.model_dump(mode="json"),
        )
        return await self._commit_update(updated, model, WorkflowStatus.CANCELLED)

    async def _load_action(
        self, workflow_id: UUID, user_id: str, expected_version: int
    ):  # type: ignore[no-untyped-def]
        model = await self.repository.get_for_user(workflow_id, user_id)
        if model is None:
            raise WorkflowNotFoundError
        if model.version != expected_version:
            raise WorkflowVersionConflictError
        if model.status in {WorkflowStatus.CANCELLED, WorkflowStatus.FAILED}:
            raise WorkflowActionError("Workflow no longer accepts actions")
        return model, TransferWorkflowState.model_validate(model.state_json)

    async def _advance_and_save(
        self, model, state: TransferWorkflowState, expected_version: int
    ) -> Workflow:  # type: ignore[no-untyped-def]
        status, advanced = await self.engine.advance(state)
        updated = await self.repository.update_if_version(
            workflow_id=model.workflow_id,
            user_id=model.user_id,
            expected_version=expected_version,
            status=status,
            state=advanced.model_dump(mode="json"),
        )
        return await self._commit_update(updated, model, status)

    async def _commit_update(self, updated, previous, status: WorkflowStatus) -> Workflow:  # type: ignore[no-untyped-def]
        if updated is None:
            await self.session.rollback()
            raise WorkflowVersionConflictError
        event = await self.publisher.persist(
            event_type=self._event_type(status),
            conversation_id=previous.conversation_id,
            task_id=previous.source_task_id,
            data=self._event_data(updated),
        )
        await self.session.commit()
        await self.publisher.publish_persisted(event)
        return to_workflow(updated)

    @staticmethod
    def _event_type(status: WorkflowStatus) -> str:
        return {
            WorkflowStatus.WAITING_FOR_INPUT: "workflow.waiting_for_input",
            WorkflowStatus.READY_FOR_REVIEW: "workflow.ready_for_review",
            WorkflowStatus.FAILED: "workflow.failed",
            WorkflowStatus.CANCELLED: "workflow.cancelled",
        }.get(status, "workflow.updated")

    @staticmethod
    def _event_data(model) -> dict[str, object]:  # type: ignore[no-untyped-def]
        data: dict[str, object] = {
            "workflow_id": str(model.workflow_id),
            "workflow_type": model.workflow_type.value,
            "status": model.status.value,
            "version": model.version,
        }
        required = model.state_json.get("required_input")
        if isinstance(required, dict) and required.get("type"):
            data["required_input_type"] = required["type"]
        return data
