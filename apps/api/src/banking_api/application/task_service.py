from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.domain.event import Event
from banking_api.domain.task import Task
from banking_api.persistence.repositories.events import EventRepository
from banking_api.persistence.repositories.tasks import TaskRepository
from banking_api.runtime.event_publisher import to_event


class TaskNotFoundError(Exception):
    pass


def to_task(model) -> Task:  # type: ignore[no-untyped-def]
    return Task(
        task_id=model.task_id,
        conversation_id=model.conversation_id,
        task_type=model.task_type,
        status=model.status,
        input=model.input_json,
        output=model.output_json,
        error=model.error_json,
        progress_message=model.progress_message,
        version=model.version,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class TaskService:
    def __init__(self, session: AsyncSession) -> None:
        self.tasks = TaskRepository(session)

    async def get(self, task_id: UUID, *, user_id: str) -> Task:
        model = await self.tasks.get_for_user(task_id, user_id)
        if model is None:
            raise TaskNotFoundError
        return to_task(model)

    async def list(self, *, user_id: str, conversation_id: UUID | None = None) -> list[Task]:
        models = await self.tasks.list_for_user(user_id, conversation_id)
        return [to_task(model) for model in models]

    async def list_events(self, task_id: UUID, *, user_id: str) -> list[Event]:
        model = await self.tasks.get_for_user(task_id, user_id)
        if model is None:
            raise TaskNotFoundError
        events = await EventRepository(self.tasks.session).list_for_task(task_id)
        return [to_event(event) for event in events]
