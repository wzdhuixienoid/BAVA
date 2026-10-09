from uuid import UUID

from fastapi import APIRouter, HTTPException

from banking_api.api.dependencies import (
    PrincipalDependency,
    SessionDependency,
    TransferWorkflowEngineDependency,
)
from banking_api.application.operation_service import OperationActionError
from banking_api.application.schedule_service import (
    ScheduleAction,
    ScheduledTransfer,
    ScheduleService,
)
from banking_api.security.guard import SecurityWriteLockedError

router = APIRouter(prefix="/scheduled-transfers", tags=["scheduled-transfers"])


@router.get("", response_model=list[ScheduledTransfer])
async def list_schedules(
    session: SessionDependency,
    principal: PrincipalDependency,
    engine: TransferWorkflowEngineDependency,
):
    return await ScheduleService(session, engine).list(principal.user_id)


@router.get("/{schedule_id}", response_model=ScheduledTransfer)
async def get_schedule(
    schedule_id: UUID,
    session: SessionDependency,
    principal: PrincipalDependency,
    engine: TransferWorkflowEngineDependency,
):
    try:
        return await ScheduleService(session, engine).get(schedule_id, principal.user_id)
    except OperationActionError as exc:
        raise HTTPException(404, detail=str(exc)) from exc


@router.post("/{schedule_id}/actions/{action}", response_model=ScheduledTransfer)
async def schedule_action(
    schedule_id: UUID,
    action: str,
    body: ScheduleAction,
    session: SessionDependency,
    principal: PrincipalDependency,
    engine: TransferWorkflowEngineDependency,
):
    try:
        service = ScheduleService(session, engine)
        if action == "authorize":
            return await service.authorize(schedule_id, principal.user_id, body.expected_version)
        if action == "cancel-series":
            return await service.cancel_series(
                schedule_id, principal.user_id, body.expected_version
            )
        if action == "delete":
            return await service.delete_cancelled(
                schedule_id, principal.user_id, body.expected_version
            )
        if action == "cancel":
            return await service.cancel(schedule_id, principal.user_id, body.expected_version)
        raise HTTPException(404)
    except (OperationActionError, SecurityWriteLockedError) as exc:
        raise HTTPException(
            423 if isinstance(exc, SecurityWriteLockedError) else 409, detail=str(exc)
        ) from exc
