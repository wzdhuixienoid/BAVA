import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from banking_api.domain.enums import MessageRole, TaskStatus
from banking_api.persistence.repositories.messages import MessageRepository
from banking_api.persistence.repositories.tasks import TaskRepository
from banking_api.runtime.event_bus import EventBus
from banking_api.runtime.event_publisher import EventPublisher


class BootstrapRuntime:
    """Temporary deterministic runtime; replace it rather than extending it into an agent."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bus: EventBus,
        *,
        delay_seconds: float = 0.15,
    ) -> None:
        self.session_factory = session_factory
        self.bus = bus
        self.delay_seconds = delay_seconds

    async def run(self, task_id: UUID, *, fail: bool = False) -> None:
        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            publisher = EventPublisher(session, self.bus)
            task = await tasks.get(task_id)
            if task is None:
                return
            await tasks.transition(task, TaskStatus.RUNNING)
            started = await publisher.persist(
                event_type="task.started",
                conversation_id=task.conversation_id,
                task_id=task.task_id,
                data={"status": task.status.value, "version": task.version},
            )
            await session.commit()
            await publisher.publish_persisted(started)

        try:
            if self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
            if fail:
                raise RuntimeError("Controlled bootstrap processing failure")

            async with self.session_factory() as session:
                tasks = TaskRepository(session)
                messages = MessageRepository(session)
                publisher = EventPublisher(session, self.bus)
                task = await tasks.get(task_id)
                if task is None:
                    return
                assistant = await messages.create(
                    conversation_id=task.conversation_id,
                    role=MessageRole.ASSISTANT,
                    content="Bootstrap runtime received your message.",
                )
                await tasks.transition(
                    task,
                    TaskStatus.COMPLETED,
                    output={"message_id": str(assistant.message_id)},
                )
                completed = await publisher.persist(
                    event_type="task.completed",
                    conversation_id=task.conversation_id,
                    task_id=task.task_id,
                    data={"status": task.status.value, "version": task.version},
                )
                message_completed = await publisher.persist(
                    event_type="conversation.message.completed",
                    conversation_id=task.conversation_id,
                    task_id=task.task_id,
                    data={
                        "message_id": str(assistant.message_id),
                        "role": assistant.role.value,
                    },
                )
                await session.commit()
                await publisher.publish_persisted(completed, message_completed)
        except Exception as exc:
            await self._fail(task_id, exc)

    async def _fail(self, task_id: UUID, exc: Exception) -> None:
        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            publisher = EventPublisher(session, self.bus)
            task = await tasks.get(task_id)
            if task is None:
                return
            await tasks.transition(
                task,
                TaskStatus.FAILED,
                error={"type": type(exc).__name__, "message": str(exc)},
            )
            failed = await publisher.persist(
                event_type="task.failed",
                conversation_id=task.conversation_id,
                task_id=task.task_id,
                data={"status": task.status.value, "version": task.version},
            )
            await session.commit()
            await publisher.publish_persisted(failed)
