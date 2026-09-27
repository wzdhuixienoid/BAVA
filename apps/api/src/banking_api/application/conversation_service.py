from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.domain.conversation import Conversation, ConversationDetail
from banking_api.domain.enums import MessageRole, RuntimeBackend
from banking_api.domain.message import Message, MessageAccepted
from banking_api.persistence.repositories.conversations import ConversationRepository
from banking_api.persistence.repositories.messages import MessageRepository
from banking_api.persistence.repositories.tasks import TaskRepository
from banking_api.runtime.event_bus import EventBus
from banking_api.runtime.event_publisher import EventPublisher

BANKING_REQUEST_TASK_TYPE = "BANKING_REQUEST"


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

    async def get(self, *, conversation_id: UUID, user_id: str) -> ConversationDetail:
        model = await self.conversations.get_for_user(conversation_id, user_id)
        if model is None:
            raise ConversationNotFoundError
        messages = await self.messages.list_for_conversation(conversation_id)
        return ConversationDetail(
            **to_conversation(model).model_dump(),
            messages=list(map(to_message, messages)),
        )

    async def accept_message(
        self, *, conversation_id: UUID, user_id: str, content: str
    ) -> MessageAccepted:
        conversation = await self.conversations.get_for_user(conversation_id, user_id)
        if conversation is None:
            raise ConversationNotFoundError

        request_id = uuid4()
        message = await self.messages.create(
            conversation_id=conversation_id, role=MessageRole.USER, content=content
        )
        task = await self.tasks.create(
            conversation_id=conversation_id,
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
