from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from banking_api.api.dependencies import (
    EventBusDependency,
    PrincipalDependency,
    SessionDependency,
    TransferWorkflowEngineDependency,
)
from banking_api.application.operation_service import (
    OperationActionError,
    OperationLeaseLostError,
    OperationNotFoundError,
    OperationService,
    OperationVersionConflictError,
)
from banking_api.domain.operation import OperationResource, ReconcileOperationAction

router = APIRouter(prefix="/operations", tags=["operations"])


def _raise_error(exc: Exception) -> NoReturn:
    if isinstance(exc, OperationNotFoundError):
        raise HTTPException(status_code=404, detail="未找到该操作") from exc
    if isinstance(exc, (OperationVersionConflictError, OperationLeaseLostError)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="操作状态已更新，请刷新后重试",
        ) from exc
    raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{operation_id}", response_model=OperationResource)
async def get_operation(
    operation_id: UUID,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
    engine: TransferWorkflowEngineDependency,
) -> OperationResource:
    try:
        return await OperationService(session, bus, engine).get(
            operation_id, user_id=principal.user_id
        )
    except OperationNotFoundError as exc:
        _raise_error(exc)


@router.post("/{operation_id}/actions/reconcile", response_model=OperationResource)
async def reconcile_operation(
    operation_id: UUID,
    body: ReconcileOperationAction,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
    engine: TransferWorkflowEngineDependency,
) -> OperationResource:
    try:
        return await OperationService(session, bus, engine).reconcile(
            operation_id,
            user_id=principal.user_id,
            expected_version=body.expected_version,
        )
    except (
        OperationNotFoundError,
        OperationVersionConflictError,
        OperationLeaseLostError,
        OperationActionError,
    ) as exc:
        _raise_error(exc)
