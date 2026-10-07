import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.domain.enums import MessageRole
from banking_api.persistence.models import ConversationModel, MessageModel
from banking_api.runtime.event_publisher import EventPublisher


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, user_id: str, title: str) -> ConversationModel:
        conversation = ConversationModel(
            user_id=user_id, title=title, title_is_custom=title not in {"新对话", "订阅管理"}
        )
        self.session.add(conversation)
        await self.session.flush()
        return conversation

    async def name_first_reply(self, conversation_id: UUID) -> None:
        # Lock before inserting the assistant message; serialize against rename/delete.
        model = await self.session.scalar(
            select(ConversationModel)
            .where(
                ConversationModel.conversation_id == conversation_id,
                ConversationModel.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if model is None or model.title_is_custom:
            return
        previous_reply = await self.session.scalar(
            select(MessageModel.message_id)
            .where(
                MessageModel.conversation_id == conversation_id,
                MessageModel.role == MessageRole.ASSISTANT,
            )
            .limit(1)
        )
        if previous_reply is not None:
            return
        first_request = await self.session.scalar(
            select(MessageModel.content)
            .where(
                MessageModel.conversation_id == conversation_id,
                MessageModel.role == MessageRole.USER,
            )
            .order_by(MessageModel.created_at, MessageModel.message_id)
            .limit(1)
        )
        if not first_request:
            return
        title = " ".join(first_request.split())
        title = re.sub(r"^(?:请帮我|帮我|请问|请)", "", title).strip()
        title = re.sub(r"\d{6,}", "****", title)
        model.title = title[:24] + ("…" if len(title) > 24 else "") or "银行咨询"
        await EventPublisher(self.session).persist(
            event_type="conversation.updated",
            conversation_id=conversation_id,
            task_id=None,
            data={"title": model.title},
        )

    async def get_for_user(
        self,
        conversation_id: UUID,
        user_id: str,
        *,
        for_update: bool = False,
        include_deleted: bool = False,
    ) -> ConversationModel | None:
        statement = select(ConversationModel).where(
            ConversationModel.conversation_id == conversation_id,
            ConversationModel.user_id == user_id,
        )
        if not include_deleted:
            statement = statement.where(ConversationModel.deleted_at.is_(None))
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get(self, conversation_id: UUID) -> ConversationModel | None:
        return await self.session.get(ConversationModel, conversation_id)

    async def list_for_user(self, user_id: str) -> list[ConversationModel]:
        result = await self.session.execute(
            select(ConversationModel)
            .where(ConversationModel.user_id == user_id, ConversationModel.deleted_at.is_(None))
            .order_by(ConversationModel.updated_at.desc())
        )
        return list(result.scalars())
