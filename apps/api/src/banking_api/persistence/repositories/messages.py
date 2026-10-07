from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.domain.enums import MessageRole
from banking_api.persistence.models import MessageModel
from banking_api.persistence.repositories.conversations import ConversationRepository


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, *, conversation_id: UUID, role: MessageRole, content: str
    ) -> MessageModel:
        if role is MessageRole.ASSISTANT:
            await ConversationRepository(self.session).name_first_reply(conversation_id)
        message = MessageModel(conversation_id=conversation_id, role=role, content=content)
        self.session.add(message)
        await self.session.flush()
        return message

    async def get(self, message_id: UUID) -> MessageModel | None:
        return await self.session.get(MessageModel, message_id)

    async def list_for_conversation(self, conversation_id: UUID) -> list[MessageModel]:
        result = await self.session.execute(
            select(MessageModel)
            .where(MessageModel.conversation_id == conversation_id)
            .order_by(MessageModel.created_at, MessageModel.message_id)
        )
        return list(result.scalars())
