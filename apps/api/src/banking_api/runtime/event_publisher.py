from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.domain.event import Event
from banking_api.persistence.models import EventModel
from banking_api.persistence.repositories.events import EventRepository
from banking_api.persistence.repositories.outbox import OutboxRepository


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
    """Atomically records a durable Event and its realtime publication intent."""

    def __init__(self, session: AsyncSession) -> None:
        self.events = EventRepository(session)
        self.outbox = OutboxRepository(session)

    async def persist(
        self,
        *,
        event_type: str,
        conversation_id: UUID,
        task_id: UUID | None,
        data: dict[str, Any],
    ) -> EventModel:
        event = await self.events.create(
            event_type=event_type,
            conversation_id=conversation_id,
            task_id=task_id,
            data=data,
        )
        await self.outbox.enqueue(
            event_id=event.event_id,
            next_publish_at=event.created_at,
        )
        return event
