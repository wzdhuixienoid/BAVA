from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from banking_api.domain.enums import TaskStatus
from banking_api.persistence.repositories.tasks import TaskRepository
from banking_api.runtime.event_bus import EventBus
from banking_api.runtime.event_publisher import EventPublisher


class TaskReconciliationService:
    """Marks work owned by a previous process lifecycle as interrupted."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bus: EventBus,
    ) -> None:
        self.session_factory = session_factory
        self.bus = bus

    async def reconcile(self) -> int:
        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            publisher = EventPublisher(session)
            interrupted_events = []
            stale_tasks = await tasks.list_stale()
            for task in stale_tasks:
                error = {
                    "category": "RUNTIME",
                    "code": "RUNTIME_INTERRUPTED",
                    "retryable": True,
                }
                await tasks.transition(task, TaskStatus.INTERRUPTED, error=error)
                interrupted_events.append(
                    await publisher.persist(
                        event_type="task.interrupted",
                        conversation_id=task.conversation_id,
                        task_id=task.task_id,
                        data={
                            "status": task.status.value,
                            "version": task.version,
                            "code": error["code"],
                            "runtime_backend": task.runtime_backend.value,
                        },
                    )
                )
            await session.commit()
            return len(stale_tasks)
