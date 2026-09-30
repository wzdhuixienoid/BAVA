from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.domain.enums import TaskStatus
from banking_api.persistence.models import PlanModel, TaskModel


class PlanWakeService:
    """Reschedule the existing source Task inside the Workflow event transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def wake(self, task_id: UUID) -> None:
        pointer = await self.session.scalar(
            select(PlanModel).where(PlanModel.source_task_id == task_id)
        )
        if pointer is None:
            return
        task = await self.session.scalar(
            select(TaskModel)
            .where(TaskModel.task_id == task_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        plan = await self.session.scalar(
            select(PlanModel)
            .where(PlanModel.plan_id == pointer.plan_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if task is None or plan is None or plan.manual_takeover:
            return
        if task.status not in {TaskStatus.WAITING_USER, TaskStatus.WAITING_EXTERNAL}:
            return
        from banking_api.application.plan_service import reschedule_task

        await reschedule_task(self.session, task, "CHILD_WORKFLOW_CHANGED")
