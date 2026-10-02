from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.persistence.models import PlanModel, PlanStepDependencyModel, PlanStepModel
from banking_api.planning.models import (
    CapabilityStepProposal,
    PlanStatus,
    PlanStepStatus,
    ValidatedPlan,
)
from banking_api.planning.registry import PlanCapabilityRegistry


class PlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def by_task(self, task_id: UUID) -> PlanModel | None:
        return await self.session.scalar(
            select(PlanModel).where(PlanModel.source_task_id == task_id)
        )

    async def get(self, plan_id: UUID, user_id: str, *, lock: bool = False) -> PlanModel | None:
        query = select(PlanModel).where(PlanModel.plan_id == plan_id, PlanModel.user_id == user_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return await self.session.scalar(query)

    async def list(self, user_id: str, conversation_id: UUID | None = None) -> list[PlanModel]:
        query = select(PlanModel).where(PlanModel.user_id == user_id)
        if conversation_id is not None:
            query = query.where(PlanModel.conversation_id == conversation_id)
        return list((await self.session.scalars(query.order_by(PlanModel.created_at.desc()))).all())

    async def steps(self, plan_id: UUID) -> list[PlanStepModel]:
        query = select(PlanStepModel).where(PlanStepModel.plan_id == plan_id)
        return list((await self.session.scalars(query.order_by(PlanStepModel.ordinal))).all())

    async def dependencies(self, plan_id: UUID) -> dict[UUID, list[UUID]]:
        rows = await self.session.execute(
            select(PlanStepDependencyModel)
            .join(PlanStepModel, PlanStepModel.step_id == PlanStepDependencyModel.step_id)
            .where(PlanStepModel.plan_id == plan_id)
        )
        dependencies: dict[UUID, list[UUID]] = {}
        for row in rows.scalars():
            dependencies.setdefault(row.step_id, []).append(row.depends_on_step_id)
        return dependencies

    async def create(
        self, validated: ValidatedPlan, *, task_id: UUID, conversation_id: UUID, user_id: str
    ) -> PlanModel:
        plan = PlanModel(
            user_id=user_id,
            conversation_id=conversation_id,
            source_task_id=task_id,
            goal_summary=validated.proposal.goal_summary,
            status=PlanStatus.RUNNING,
        )
        self.session.add(plan)
        await self.session.flush()
        registry = PlanCapabilityRegistry()
        steps = {}
        for ordinal, proposal in enumerate(validated.proposal.steps):
            step = PlanStepModel(
                plan_id=plan.plan_id,
                step_key=proposal.step_key,
                ordinal=ordinal,
                display_title=proposal.display_title,
                step_kind=proposal.kind,
                capability=proposal.capability
                if isinstance(proposal, CapabilityStepProposal)
                else None,
                executor_kind=(
                    registry.get(proposal.capability).executor_kind
                    if isinstance(proposal, CapabilityStepProposal)
                    else "CONDITION"
                ),
                condition_spec_json=(
                    None
                    if isinstance(proposal, CapabilityStepProposal)
                    else proposal.condition.model_dump(mode="json")
                ),
                status=PlanStepStatus.PENDING,
                subtask_query=proposal.subtask_query
                if isinstance(proposal, CapabilityStepProposal)
                else None,
            )
            self.session.add(step)
            steps[step.step_key] = step
        await self.session.flush()
        for proposal in validated.proposal.steps:
            if isinstance(proposal, CapabilityStepProposal) and proposal.guard_condition_step_key:
                steps[proposal.step_key].guard_condition_step_id = steps[
                    proposal.guard_condition_step_key
                ].step_id
            for dependency in proposal.depends_on:
                self.session.add(
                    PlanStepDependencyModel(
                        step_id=steps[proposal.step_key].step_id,
                        depends_on_step_id=steps[dependency].step_id,
                    )
                )
        await self.session.flush()
        return plan
