import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from banking_api.domain.event import Event


class EventBus:
    """Single-process bootstrap transport; durable truth remains in PostgreSQL."""

    def __init__(self) -> None:
        self._subscribers: dict[UUID, set[asyncio.Queue[Event]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def subscribe(self, conversation_id: UUID) -> AsyncIterator[asyncio.Queue[Event]]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subscribers[conversation_id].add(queue)
        try:
            yield queue
        finally:
            async with self._lock:
                subscribers = self._subscribers.get(conversation_id)
                if subscribers is not None:
                    subscribers.discard(queue)
                    if not subscribers:
                        self._subscribers.pop(conversation_id, None)

    async def publish(self, event: Event) -> None:
        async with self._lock:
            subscribers = tuple(self._subscribers.get(event.conversation_id, ()))
        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # A slow live consumer can recover authoritative state through resource APIs.
                continue


event_bus = EventBus()

