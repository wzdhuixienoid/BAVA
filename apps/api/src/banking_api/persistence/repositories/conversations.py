from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.persistence.models import ConversationModel


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, user_id: str, title: str) -> ConversationModel:
        conversation = ConversationModel(user_id=user_id, title=title)
        self.session.add(conversation)
        await self.session.flush()
        return conversation

    async def get_for_user(self, conversation_id: UUID, user_id: str) -> ConversationModel | None:
        result = await self.session.execute(
            select(ConversationModel).where(
                ConversationModel.conversation_id == conversation_id,
                ConversationModel.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get(self, conversation_id: UUID) -> ConversationModel | None:
        return await self.session.get(ConversationModel, conversation_id)

    async def list_for_user(self, user_id: str) -> list[ConversationModel]:
        result = await self.session.execute(
            select(ConversationModel)
            .where(ConversationModel.user_id == user_id)
            .order_by(ConversationModel.updated_at.desc())
        )
        return list(result.scalars())
