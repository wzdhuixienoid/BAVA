from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from banking_api.persistence.models import utc_now
from banking_api.persistence.repositories.tasks import TaskRepository
from banking_api.runtime.event_bus import EventBus


class TaskReconciliationService:
    """Makes legacy recoverable Tasks schedulable without changing their status."""

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
            stale_tasks = await tasks.list_stale()
            for task in stale_tasks:
                task.next_run_at = utc_now()
            await session.commit()
            return len(stale_tasks)
