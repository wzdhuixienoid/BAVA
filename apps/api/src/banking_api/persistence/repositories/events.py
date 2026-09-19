from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.persistence.models import EventModel


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        event_type: str,
        conversation_id: UUID,
        task_id: UUID | None,
        data: dict[str, Any],
    ) -> EventModel:
        event = EventModel(
            event_type=event_type,
            conversation_id=conversation_id,
            task_id=task_id,
            data_json=data,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def list_for_conversation(self, conversation_id: UUID) -> list[EventModel]:
        result = await self.session.execute(
            select(EventModel)
            .where(EventModel.conversation_id == conversation_id)
            .order_by(EventModel.sequence)
        )
        return list(result.scalars())

    async def list_for_task(self, task_id: UUID) -> list[EventModel]:
        result = await self.session.execute(
            select(EventModel).where(EventModel.task_id == task_id).order_by(EventModel.sequence)
        )
        return list(result.scalars())

