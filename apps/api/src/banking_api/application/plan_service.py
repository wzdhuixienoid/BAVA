from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.domain.enums import TaskStatus
from banking_api.domain.plan import Plan, PlanStep
from banking_api.persistence.models import PlanModel, PlanStepModel, TaskModel, utc_now
from banking_api.persistence.repositories.plans import PlanRepository
from banking_api.planning.models import PlanCapability, PlanStatus, PlanStepStatus
from banking_api.planning.registry import PlanCapabilityRegistry
from banking_api.runtime.event_publisher import EventPublisher


class PlanNotFoundError(Exception):
    pass


class PlanActionError(Exception):
    pass


def descendants(target: UUID, dependencies: dict[UUID, list[UUID]]) -> set[UUID]:
    affected = {target}
    while True:
        expanded = affected | {
            step for step, parents in dependencies.items() if affected.intersection(parents)
        }
        if expanded == affected:
            return affected
        affected = expanded


def rollback_safe(
    target: UUID, steps: list[PlanStepModel], dependencies: dict[UUID, list[UUID]]
) -> bool:
    affected = descendants(target, dependencies)
    registry = PlanCapabilityRegistry()
    return all(
        registry.get(PlanCapability(step.capability)).read_only and step.linked_workflow_id is None
        for step in steps
        if step.step_id in affected
    )


async def plan_event(session: AsyncSession, plan: PlanModel, reason: str) -> None:
    await EventPublisher(session).persist(
        event_type="plan.state_changed",
        conversation_id=plan.conversation_id,
        task_id=plan.source_task_id,
        data={
            "plan_id": str(plan.plan_id),
            "to_status": plan.status,
            "reason_code": reason,
            "version": plan.version,
        },
    )


async def step_event(session: AsyncSession, plan: PlanModel, step: PlanStepModel) -> None:
    await EventPublisher(session).persist(
        event_type="plan.step_state_changed",
        conversation_id=plan.conversation_id,
        task_id=plan.source_task_id,
        data={
            "plan_id": str(plan.plan_id),
            "step_id": str(step.step_id),
            "capability": step.capability,
            "to_status": step.status,
            "reason_code": step.error_code,
            "linked_workflow_id": str(step.linked_workflow_id) if step.linked_workflow_id else None,
        },
    )


async def reschedule_task(session: AsyncSession, task: TaskModel, reason: str) -> None:
    task.status = TaskStatus.PENDING
    task.next_run_at = utc_now()
    task.lease_owner = None
    task.lease_expires_at = None
    task.error_json = None
    task.output_json = None
    task.progress_message = "计划等待继续执行"
    task.version += 1
    await EventPublisher(session).persist(
        event_type="task.rescheduled",
        conversation_id=task.conversation_id,
        task_id=task.task_id,
        data={"reason_code": reason, "version": task.version},
    )


class PlanService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.plans = PlanRepository(session)

    async def resource(self, plan: PlanModel) -> Plan:
        steps = await self.plans.steps(plan.plan_id)
        dependencies = await self.plans.dependencies(plan.plan_id)
        return Plan(
            plan_id=plan.plan_id,
            conversation_id=plan.conversation_id,
            source_task_id=plan.source_task_id,
            goal_summary=plan.goal_summary,
            status=plan.status,
            version=plan.version,
            manual_takeover=plan.manual_takeover,
            created_at=plan.created_at,
            updated_at=plan.updated_at,
            completed_at=plan.completed_at,
            steps=[
                PlanStep(
                    step_id=step.step_id,
                    step_key=step.step_key,
                    display_title=step.display_title,
                    capability=step.capability,
                    status=step.status,
                    depends_on=dependencies.get(step.step_id, []),
                    linked_workflow_id=step.linked_workflow_id,
                    result_summary=step.output_json,
                    error_code=step.error_code,
                    rollback_allowed=rollback_safe(step.step_id, steps, dependencies),
                )
                for step in steps
            ],
        )

    async def get(self, plan_id: UUID, user_id: str) -> Plan:
        plan = await self.plans.get(plan_id, user_id)
        if plan is None:
            raise PlanNotFoundError
        return await self.resource(plan)

    async def list(self, user_id: str, conversation_id: UUID | None = None) -> list[Plan]:
        return [
            await self.resource(plan) for plan in await self.plans.list(user_id, conversation_id)
        ]

    async def action(
        self, plan_id: UUID, user_id: str, action: str, target_step_id: UUID | None = None
    ) -> Plan:
        pointer = await self.plans.get(plan_id, user_id)
        if pointer is None:
            raise PlanNotFoundError
        # Every Plan mutator locks Task then Plan. Invalidating the current Task
        # lease also fences an in-flight read call when a user interrupts it.
        task = await self.session.scalar(
            select(TaskModel)
            .where(TaskModel.task_id == pointer.source_task_id, TaskModel.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        plan = await self.plans.get(plan_id, user_id, lock=True)
        if task is None or plan is None:
            raise PlanNotFoundError
        if action == "take-over":
            if plan.status in {PlanStatus.COMPLETED, PlanStatus.FAILED, PlanStatus.CANCELLED}:
                raise PlanActionError("PLAN_ALREADY_TERMINAL")
            plan.status = PlanStatus.PAUSED
            plan.manual_takeover = True
            task.status = TaskStatus.WAITING_USER
            task.next_run_at = None
            task.lease_owner = None
            task.lease_expires_at = None
            task.version += 1
            task.progress_message = "自动任务编排已暂停，你可以继续手动处理当前业务步骤"
        elif action == "resume":
            if plan.status != PlanStatus.PAUSED:
                raise PlanActionError("PLAN_NOT_PAUSED")
            plan.manual_takeover = False
            plan.status = PlanStatus.RUNNING
            await reschedule_task(self.session, task, "PLAN_RESUMED")
        elif action == "rollback":
            steps = await self.plans.steps(plan_id)
            dependencies = await self.plans.dependencies(plan_id)
            if target_step_id not in {step.step_id for step in steps}:
                raise PlanActionError("PLAN_STEP_NOT_FOUND")
            assert target_step_id is not None
            if not rollback_safe(target_step_id, steps, dependencies):
                raise PlanActionError("PLAN_ROLLBACK_NOT_SAFE")
            affected = descendants(target_step_id, dependencies)
            for step in steps:
                if step.step_id in affected:
                    step.status = PlanStepStatus.PENDING
                    step.output_json = None
                    step.error_code = None
                    step.error_message = None
                    step.started_at = None
                    step.completed_at = None
                    await step_event(self.session, plan, step)
            plan.manual_takeover = False
            plan.status = PlanStatus.RUNNING
            plan.completed_at = None
            await reschedule_task(self.session, task, "PLAN_ROLLED_BACK")
        else:
            raise PlanActionError("PLAN_ACTION_UNSUPPORTED")
        plan.version += 1
        plan.updated_at = utc_now()
        await plan_event(self.session, plan, "PLAN_" + action.upper().replace("-", "_"))
        await self.session.commit()
        return await self.resource(plan)
