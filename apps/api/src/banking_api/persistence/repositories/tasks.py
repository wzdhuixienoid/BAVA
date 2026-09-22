from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.domain.enums import RuntimeBackend, TaskStatus
from banking_api.persistence.models import ConversationModel, TaskModel


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        conversation_id: UUID,
        task_type: str,
        input_data: dict[str, Any],
        runtime_backend: RuntimeBackend = RuntimeBackend.MANUAL,
    ) -> TaskModel:
        task = TaskModel(
            conversation_id=conversation_id,
            task_type=task_type,
            runtime_backend=runtime_backend,
            status=TaskStatus.PENDING,
            input_json=input_data,
            version=1,
        )
        self.session.add(task)
        await self.session.flush()
        return task

    async def list_stale(self) -> list[TaskModel]:
        result = await self.session.execute(
            select(TaskModel).where(
                TaskModel.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING])
            )
        )
        return list(result.scalars())

    async def get(self, task_id: UUID) -> TaskModel | None:
        return await self.session.get(TaskModel, task_id)

    async def get_for_user(self, task_id: UUID, user_id: str) -> TaskModel | None:
        result = await self.session.execute(
            select(TaskModel)
            .join(ConversationModel)
            .where(TaskModel.task_id == task_id, ConversationModel.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self, user_id: str, conversation_id: UUID | None = None
    ) -> list[TaskModel]:
        statement = (
            select(TaskModel)
            .join(ConversationModel)
            .where(ConversationModel.user_id == user_id)
        )
        if conversation_id is not None:
            statement = statement.where(TaskModel.conversation_id == conversation_id)
        result = await self.session.execute(statement.order_by(TaskModel.created_at.desc()))
        return list(result.scalars())

    async def transition(
        self,
        task: TaskModel,
        status: TaskStatus,
        *,
        output: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        progress_message: str | None = None,
    ) -> TaskModel:
        task.status = status
        task.output_json = output
        task.error_json = error
        task.progress_message = progress_message
        task.version += 1
        await self.session.flush()
        return task

    async def update_progress(self, task: TaskModel, message: str) -> TaskModel:
        task.progress_message = message
        task.version += 1
        await self.session.flush()
        return task
