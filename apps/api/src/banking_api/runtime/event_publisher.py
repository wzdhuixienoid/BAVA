from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.domain.event import Event
from banking_api.persistence.models import EventModel
from banking_api.persistence.repositories.events import EventRepository
from banking_api.runtime.event_bus import EventBus


def to_event(model: EventModel) -> Event:
    return Event(
        event_id=model.event_id,
        event_type=model.event_type,
        timestamp=model.created_at,
        conversation_id=model.conversation_id,
        task_id=model.task_id,
        sequence=model.sequence,
        data=model.data_json,
    )


class EventPublisher:
    def __init__(self, session: AsyncSession, bus: EventBus) -> None:
        self.events = EventRepository(session)
        self.bus = bus

    async def persist(
        self,
        *,
        event_type: str,
        conversation_id: UUID,
        task_id: UUID | None,
        data: dict[str, Any],
    ) -> EventModel:
        return await self.events.create(
            event_type=event_type,
            conversation_id=conversation_id,
            task_id=task_id,
            data=data,
        )

    async def publish_persisted(self, *models: EventModel) -> None:
        for model in models:
            await self.bus.publish(to_event(model))

