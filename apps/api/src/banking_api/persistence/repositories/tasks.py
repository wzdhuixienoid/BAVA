from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.domain.enums import (
    ExecutorType,
    RequestedOutput,
    RuntimeBackend,
    TaskStatus,
)
from banking_api.persistence.models import TaskModel, utc_now

RUNNABLE_TASK_STATUSES = (
    TaskStatus.PENDING,
    TaskStatus.RUNNING,
    TaskStatus.INTERRUPTED,
)
TERMINAL_TASK_STATUSES = (
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
    TaskStatus.SKIPPED,
)


@dataclass(frozen=True)
class TaskExecutionClaim:
    task_id: UUID
    conversation_id: UUID
    user_id: str
    lease_owner: str
    attempt: int
    version: int
    runtime_backend: RuntimeBackend
    reclaimed: bool


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        conversation_id: UUID,
        user_id: str,
        task_type: str,
        input_data: dict[str, Any],
        runtime_backend: RuntimeBackend = RuntimeBackend.MANUAL,
    ) -> TaskModel:
        task = TaskModel(
            conversation_id=conversation_id,
            user_id=user_id,
            task_type=task_type,
            runtime_backend=runtime_backend,
            status=TaskStatus.PENDING,
            input_json=input_data,
            next_run_at=utc_now(),
            execution_attempts=0,
            version=1,
        )
        self.session.add(task)
        await self.session.flush()
        return task

    async def claim_due(
        self,
        *,
        lease_owner: str,
        now: datetime,
        lease_expires_at: datetime,
        limit: int,
        task_id: UUID | None = None,
    ) -> list[TaskExecutionClaim]:
        statement = select(TaskModel).where(
            TaskModel.status.in_(RUNNABLE_TASK_STATUSES),
            TaskModel.next_run_at.is_not(None),
            TaskModel.next_run_at <= now,
            or_(
                TaskModel.lease_expires_at.is_(None),
                TaskModel.lease_expires_at <= now,
            ),
        )
        if task_id is not None:
            statement = statement.where(TaskModel.task_id == task_id)
        result = await self.session.execute(
            statement.order_by(TaskModel.next_run_at, TaskModel.created_at, TaskModel.task_id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        claims: list[TaskExecutionClaim] = []
        for task in result.scalars():
            reclaimed = (
                task.status in (TaskStatus.RUNNING, TaskStatus.INTERRUPTED)
                or task.lease_owner is not None
            )
            task.status = TaskStatus.RUNNING
            task.progress_message = "正在理解请求"
            task.error_json = None
            task.lease_owner = lease_owner
            task.lease_expires_at = lease_expires_at
            task.last_attempt_at = now
            task.next_run_at = now
            task.execution_attempts += 1
            task.version += 1
            claims.append(
                TaskExecutionClaim(
                    task_id=task.task_id,
                    conversation_id=task.conversation_id,
                    user_id=task.user_id,
                    lease_owner=lease_owner,
                    attempt=task.execution_attempts,
                    version=task.version,
                    runtime_backend=task.runtime_backend,
                    reclaimed=reclaimed,
                )
            )
        await self.session.flush()
        return claims

    async def get_owned(
        self,
        *,
        task_id: UUID,
        lease_owner: str,
        attempt: int,
        now: datetime,
        for_update: bool = False,
    ) -> TaskModel | None:
        statement = select(TaskModel).where(
            TaskModel.task_id == task_id,
            TaskModel.status == TaskStatus.RUNNING,
            TaskModel.lease_owner == lease_owner,
            TaskModel.execution_attempts == attempt,
            TaskModel.lease_expires_at > now,
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def renew_lease(
        self,
        *,
        task_id: UUID,
        lease_owner: str,
        attempt: int,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        result = await self.session.execute(
            update(TaskModel)
            .where(
                TaskModel.task_id == task_id,
                TaskModel.status == TaskStatus.RUNNING,
                TaskModel.lease_owner == lease_owner,
                TaskModel.execution_attempts == attempt,
                TaskModel.lease_expires_at > now,
            )
            .values(lease_expires_at=lease_expires_at, updated_at=utc_now())
        )
        return result.rowcount == 1  # type: ignore[attr-defined]

    async def list_stale(self, *, now: datetime | None = None) -> list[TaskModel]:
        current = now or utc_now()
        result = await self.session.execute(
            select(TaskModel).where(
                TaskModel.status.in_(RUNNABLE_TASK_STATUSES),
                TaskModel.next_run_at.is_(None),
                or_(
                    TaskModel.lease_expires_at.is_(None),
                    TaskModel.lease_expires_at <= current,
                ),
            )
        )
        return list(result.scalars())

    async def get(self, task_id: UUID) -> TaskModel | None:
        return await self.session.get(TaskModel, task_id)

    async def get_for_user(self, task_id: UUID, user_id: str) -> TaskModel | None:
        result = await self.session.execute(
            select(TaskModel).where(TaskModel.task_id == task_id, TaskModel.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self, user_id: str, conversation_id: UUID | None = None
    ) -> list[TaskModel]:
        statement = select(TaskModel).where(TaskModel.user_id == user_id)
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
        if status in TERMINAL_TASK_STATUSES or status in (
            TaskStatus.WAITING_USER,
            TaskStatus.WAITING_EXTERNAL,
        ):
            task.next_run_at = None
            task.lease_owner = None
            task.lease_expires_at = None
        task.version += 1
        await self.session.flush()
        return task

    async def schedule_retry(
        self,
        task: TaskModel,
        *,
        error: dict[str, Any],
        next_run_at: datetime,
    ) -> TaskModel:
        task.status = TaskStatus.INTERRUPTED
        task.output_json = None
        task.error_json = error
        task.progress_message = None
        task.next_run_at = next_run_at
        task.lease_owner = None
        task.lease_expires_at = None
        task.version += 1
        await self.session.flush()
        return task

    async def update_progress(self, task: TaskModel, message: str) -> TaskModel:
        task.progress_message = message
        task.version += 1
        await self.session.flush()
        return task

    async def assign_executor(
        self,
        task: TaskModel,
        *,
        executor_type: ExecutorType,
        executor_id: str,
    ) -> TaskModel:
        task.executor_type = executor_type
        task.executor_id = executor_id
        task.version += 1
        await self.session.flush()
        return task

    async def assign_route(
        self,
        task: TaskModel,
        *,
        requested_output: RequestedOutput,
        executor_type: ExecutorType | None,
        executor_id: str | None,
    ) -> TaskModel:
        task.requested_output = requested_output
        task.executor_type = executor_type
        task.executor_id = executor_id
        task.version += 1
        await self.session.flush()
        return task
