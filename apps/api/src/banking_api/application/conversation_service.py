from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.domain.conversation import Conversation, ConversationDetail
from banking_api.domain.enums import (
    MessageRole,
    OperationStatus,
    RuntimeBackend,
    TaskStatus,
    WorkflowStatus,
)
from banking_api.domain.message import Message, MessageAccepted
from banking_api.persistence.models import (
    OperationModel,
    PlanModel,
    ScheduledTransferModel,
    TaskModel,
    WorkflowModel,
)
from banking_api.persistence.repositories.conversations import ConversationRepository
from banking_api.persistence.repositories.messages import MessageRepository
from banking_api.persistence.repositories.tasks import TaskRepository
from banking_api.planning.models import PlanStatus
from banking_api.runtime.event_bus import EventBus
from banking_api.runtime.event_publisher import EventPublisher

BANKING_REQUEST_TASK_TYPE = "BANKING_REQUEST"


class ConversationActiveError(Exception):
    pass


class ConversationNotFoundError(Exception):
    pass


def to_conversation(model) -> Conversation:  # type: ignore[no-untyped-def]
    return Conversation.model_validate(model)


def to_message(model) -> Message:  # type: ignore[no-untyped-def]
    return Message.model_validate(model)


class ConversationService:
    def __init__(
        self,
        session: AsyncSession,
        bus: EventBus,
        runtime_backend: RuntimeBackend = RuntimeBackend.MANUAL,
    ) -> None:
        self.session = session
        self.conversations = ConversationRepository(session)
        self.messages = MessageRepository(session)
        self.tasks = TaskRepository(session)
        self.publisher = EventPublisher(session)
        self.runtime_backend = runtime_backend

    async def create(self, *, user_id: str, title: str) -> Conversation:
        model = await self.conversations.create(user_id=user_id, title=title)
        await self.session.commit()
        return to_conversation(model)

    async def list(self, *, user_id: str) -> list[Conversation]:
        models = await self.conversations.list_for_user(user_id)
        return [to_conversation(model) for model in models]

    async def rename(self, *, conversation_id: UUID, user_id: str, title: str) -> Conversation:
        model = await self.conversations.get_for_user(conversation_id, user_id, for_update=True)
        if model is None:
            raise ConversationNotFoundError
        model.title = title
        model.title_is_custom = True
        await self.publisher.persist(
            event_type="conversation.updated",
            conversation_id=conversation_id,
            task_id=None,
            data={"title": title},
        )
        await self.session.commit()
        return to_conversation(model)

    async def get(self, *, conversation_id: UUID, user_id: str) -> ConversationDetail:
        model = await self.conversations.get_for_user(conversation_id, user_id)
        if model is None:
            raise ConversationNotFoundError
        messages = await self.messages.list_for_conversation(conversation_id)
        return ConversationDetail(
            **to_conversation(model).model_dump(),
            messages=list(map(to_message, messages)),
        )

    async def delete(self, *, conversation_id: UUID, user_id: str) -> None:
        model = await self.conversations.get_for_user(
            conversation_id, user_id, for_update=True, include_deleted=True
        )
        if model is None:
            raise ConversationNotFoundError
        if model.deleted_at is not None:
            return
        terminal_tasks = [
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.SKIPPED,
        ]
        terminal_workflows = [
            WorkflowStatus.SUCCEEDED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        ]
        terminal_plans = [PlanStatus.COMPLETED, PlanStatus.FAILED, PlanStatus.CANCELLED]
        # A durable authorized appointment survives deletion of its chat. It is
        # managed on the schedules page; pending authorization and in-flight funds
        # still retain the existing active-conversation protection.
        independent_schedules = select(ScheduledTransferModel.workflow_id).where(
            ScheduledTransferModel.user_id == user_id,
            ScheduledTransferModel.status.in_(["SCHEDULED", "CANCELLED", "EXPIRED", "FAILED"]),
            ScheduledTransferModel.operation_id.is_(None),
        )
        scheduled_tasks = select(WorkflowModel.source_task_id).where(
            WorkflowModel.workflow_id.in_(independent_schedules)
        )
        checks = [
            select(
                exists().where(
                    TaskModel.conversation_id == conversation_id,
                    TaskModel.status.not_in(terminal_tasks),
                    TaskModel.task_id.not_in(scheduled_tasks),
                )
            ),
            select(
                exists().where(
                    WorkflowModel.conversation_id == conversation_id,
                    WorkflowModel.status.not_in(terminal_workflows),
                    WorkflowModel.workflow_id.not_in(independent_schedules),
                )
            ),
            select(
                exists().where(
                    PlanModel.conversation_id == conversation_id,
                    PlanModel.status.not_in(terminal_plans),
                )
            ),
            select(
                exists().where(
                    OperationModel.workflow_id.in_(
                        select(WorkflowModel.workflow_id).where(
                            WorkflowModel.conversation_id == conversation_id
                        )
                    ),
                    OperationModel.status.not_in(
                        [OperationStatus.SUCCEEDED, OperationStatus.FAILED]
                    ),
                )
            ),
        ]
        for statement in checks:
            if await self.session.scalar(statement):
                raise ConversationActiveError
        model.deleted_at = datetime.now(UTC)
        await self.publisher.persist(
            event_type="conversation.deleted",
            conversation_id=conversation_id,
            task_id=None,
            data={},
        )
        await self.session.commit()

    async def accept_message(
        self, *, conversation_id: UUID, user_id: str, content: str
    ) -> MessageAccepted:
        conversation = await self.conversations.get_for_user(
            conversation_id, user_id, for_update=True
        )
        if conversation is None:
            raise ConversationNotFoundError

        request_id = uuid4()
        message = await self.messages.create(
            conversation_id=conversation_id, role=MessageRole.USER, content=content
        )
        task = await self.tasks.create(
            conversation_id=conversation_id,
            user_id=user_id,
            task_type=BANKING_REQUEST_TASK_TYPE,
            input_data={"message_id": str(message.message_id), "request_id": str(request_id)},
            runtime_backend=self.runtime_backend,
        )
        await self.publisher.persist(
            event_type="conversation.message.created",
            conversation_id=conversation_id,
            task_id=task.task_id,
            data={"message_id": str(message.message_id), "role": message.role.value},
        )
        await self.publisher.persist(
            event_type="task.created",
            conversation_id=conversation_id,
            task_id=task.task_id,
            data={
                "status": task.status.value,
                "version": task.version,
                "runtime_backend": task.runtime_backend.value,
            },
        )
        await self.session.commit()
        return MessageAccepted(
            message_id=message.message_id, task_id=task.task_id, request_id=request_id
        )
