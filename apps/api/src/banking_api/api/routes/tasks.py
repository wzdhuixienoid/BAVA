from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request

from banking_api.api.dependencies import PrincipalDependency, SessionDependency
from banking_api.application.task_service import TaskNotFoundError, TaskService
from banking_api.audit.models import AuditTrace
from banking_api.audit.projection import AuditProjection
from banking_api.domain.event import Event
from banking_api.domain.task import Task
from banking_api.financial.presentation import with_account_names, with_anomaly_answer

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/{task_id}/audit", response_model=AuditTrace)
async def get_task_audit(
    task_id: UUID, session: SessionDependency, principal: PrincipalDependency
) -> AuditTrace:
    try:
        return await AuditProjection(session).get(task_id, principal.user_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到该任务") from exc


@router.get("", response_model=list[Task])
async def list_tasks(
    request: Request,
    session: SessionDependency,
    principal: PrincipalDependency,
    conversation_id: Annotated[UUID | None, Query()] = None,
) -> list[Task]:
    tasks = await TaskService(session).list(
        user_id=principal.user_id, conversation_id=conversation_id
    )
    accounts = request.app.state.mock_bank.list_accounts(user_id=principal.user_id)
    return [with_anomaly_answer(with_account_names(task, accounts)) for task in tasks]


@router.get("/{task_id}", response_model=Task)
async def get_task(
    request: Request, task_id: UUID, session: SessionDependency, principal: PrincipalDependency
) -> Task:
    try:
        task = await TaskService(session).get(task_id, user_id=principal.user_id)
        accounts = request.app.state.mock_bank.list_accounts(user_id=principal.user_id)
        return with_anomaly_answer(with_account_names(task, accounts))
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到该任务") from exc


@router.get("/{task_id}/events", response_model=list[Event])
async def get_task_events(
    task_id: UUID, session: SessionDependency, principal: PrincipalDependency
) -> list[Event]:
    try:
        return await TaskService(session).list_events(task_id, user_id=principal.user_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到该任务") from exc
