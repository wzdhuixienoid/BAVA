from uuid import UUID

from fastapi import APIRouter, HTTPException

from banking_api.api.dependencies import PrincipalDependency, SessionDependency
from banking_api.application.plan_service import PlanActionError, PlanNotFoundError, PlanService
from banking_api.domain.plan import Plan, RollbackPlanAction

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("", response_model=list[Plan])
async def list_plans(
    session: SessionDependency, principal: PrincipalDependency, conversation_id: UUID | None = None
) -> list[Plan]:
    return await PlanService(session).list(principal.user_id, conversation_id)


@router.get("/{plan_id}", response_model=Plan)
async def get_plan(
    plan_id: UUID, session: SessionDependency, principal: PrincipalDependency
) -> Plan:
    try:
        return await PlanService(session).get(plan_id, principal.user_id)
    except PlanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到该计划") from exc


async def perform_action(session, principal, plan_id, action, target=None):
    try:
        return await PlanService(session).action(plan_id, principal.user_id, action, target)
    except PlanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到该计划") from exc
    except PlanActionError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc


@router.post("/{plan_id}/actions/take-over", response_model=Plan)
async def take_over(
    plan_id: UUID, session: SessionDependency, principal: PrincipalDependency
) -> Plan:
    return await perform_action(session, principal, plan_id, "take-over")


@router.post("/{plan_id}/actions/resume", response_model=Plan)
async def resume(plan_id: UUID, session: SessionDependency, principal: PrincipalDependency) -> Plan:
    return await perform_action(session, principal, plan_id, "resume")


@router.post("/{plan_id}/actions/rollback", response_model=Plan)
async def rollback(
    plan_id: UUID,
    body: RollbackPlanAction,
    session: SessionDependency,
    principal: PrincipalDependency,
) -> Plan:
    return await perform_action(session, principal, plan_id, "rollback", body.target_step_id)
