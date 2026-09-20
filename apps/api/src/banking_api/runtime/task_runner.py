from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from banking_api.application.conversation_service import to_message
from banking_api.domain.enums import MessageRole, TaskStatus
from banking_api.persistence.repositories.messages import MessageRepository
from banking_api.persistence.repositories.tasks import TaskRepository
from banking_api.runtime.agent_runtime import AgentRuntime, AgentRuntimeError
from banking_api.runtime.event_bus import EventBus
from banking_api.runtime.event_publisher import EventPublisher


class InProcessTaskRunner:
    """Runs one agent task outside the request's database session."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bus: EventBus,
        runtime: AgentRuntime,
    ) -> None:
        self.session_factory = session_factory
        self.bus = bus
        self.runtime = runtime

    async def run(self, task_id: UUID) -> None:
        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            messages = MessageRepository(session)
            publisher = EventPublisher(session, self.bus)
            task = await tasks.get(task_id)
            if task is None or task.status is not TaskStatus.PENDING:
                return
            message_id = UUID(str(task.input_json["message_id"]))
            current_message = await messages.get(message_id)
            if current_message is None:
                return
            conversation_messages = [
                to_message(message)
                for message in await messages.list_for_conversation(task.conversation_id)
            ]
            current_task = current_message.content
            conversation_id = task.conversation_id
            await tasks.transition(
                task,
                TaskStatus.RUNNING,
                progress_message="正在理解请求",
            )
            started = await publisher.persist(
                event_type="task.started",
                conversation_id=conversation_id,
                task_id=task_id,
                data={"status": task.status.value, "version": task.version},
            )
            progress = await publisher.persist(
                event_type="task.progress",
                conversation_id=conversation_id,
                task_id=task_id,
                data={"message": "正在理解请求", "version": task.version},
            )
            await session.commit()
            await publisher.publish_persisted(started, progress)

        async def event_sink(event_type: str, data: dict[str, Any]) -> None:
            await self._persist_runtime_event(
                task_id=task_id,
                conversation_id=conversation_id,
                event_type=event_type,
                data=data,
            )

        try:
            result = await self.runtime.run(
                task_id=task_id,
                conversation_id=conversation_id,
                current_task=current_task,
                conversation_messages=conversation_messages,
                authenticated=True,
                event_sink=event_sink,
            )
            async with self.session_factory() as session:
                tasks = TaskRepository(session)
                messages = MessageRepository(session)
                publisher = EventPublisher(session, self.bus)
                task = await tasks.get(task_id)
                if task is None:
                    return
                assistant = await messages.create(
                    conversation_id=conversation_id,
                    role=MessageRole.ASSISTANT,
                    content=result.answer,
                )
                await tasks.transition(
                    task,
                    TaskStatus.COMPLETED,
                    output={
                        "message_id": str(assistant.message_id),
                        "steps": result.state.step_count,
                        "tool_calls": result.state.tool_call_count,
                    },
                )
                completed = await publisher.persist(
                    event_type="task.completed",
                    conversation_id=conversation_id,
                    task_id=task_id,
                    data={"status": task.status.value, "version": task.version},
                )
                message_completed = await publisher.persist(
                    event_type="conversation.message.completed",
                    conversation_id=conversation_id,
                    task_id=task_id,
                    data={"message_id": str(assistant.message_id), "role": assistant.role.value},
                )
                await session.commit()
                await publisher.publish_persisted(completed, message_completed)
        except AgentRuntimeError as exc:
            await self._fail(task_id, conversation_id, exc.as_dict())
        except Exception:
            error = {
                "category": "INTERNAL",
                "code": "AGENT_RUNTIME_ERROR",
                "message": "Agent runtime failed",
                "retryable": False,
            }
            await event_sink(
                "agent.run.failed",
                {"code": error["code"], "category": error["category"], "retryable": False},
            )
            await self._fail(task_id, conversation_id, error)

    async def _persist_runtime_event(
        self,
        *,
        task_id: UUID,
        conversation_id: UUID,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        progress_message = None
        if event_type == "tool.call.started":
            progress_message = "正在查询账户"
        elif event_type == "tool.call.completed":
            progress_message = "正在整理结果"

        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            publisher = EventPublisher(session, self.bus)
            persisted = []
            task = await tasks.get(task_id)
            if task is None:
                return
            if progress_message is not None and task.progress_message != progress_message:
                await tasks.update_progress(task, progress_message)
                persisted.append(
                    await publisher.persist(
                        event_type="task.progress",
                        conversation_id=conversation_id,
                        task_id=task_id,
                        data={"message": progress_message, "version": task.version},
                    )
                )
            persisted.append(
                await publisher.persist(
                    event_type=event_type,
                    conversation_id=conversation_id,
                    task_id=task_id,
                    data=data,
                )
            )
            await session.commit()
            await publisher.publish_persisted(*persisted)

    async def _fail(
        self, task_id: UUID, conversation_id: UUID, error: dict[str, Any]
    ) -> None:
        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            publisher = EventPublisher(session, self.bus)
            task = await tasks.get(task_id)
            if task is None:
                return
            await tasks.transition(task, TaskStatus.FAILED, error=error)
            failed = await publisher.persist(
                event_type="task.failed",
                conversation_id=conversation_id,
                task_id=task_id,
                data={
                    "status": task.status.value,
                    "version": task.version,
                    "code": error["code"],
                },
            )
            await session.commit()
            await publisher.publish_persisted(failed)
