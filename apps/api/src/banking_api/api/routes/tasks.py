from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from banking_api.api.dependencies import PrincipalDependency, SessionDependency
from banking_api.application.task_service import TaskNotFoundError, TaskService
from banking_api.domain.task import Task

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[Task])
async def list_tasks(
    session: SessionDependency,
    principal: PrincipalDependency,
    conversation_id: Annotated[UUID | None, Query()] = None,
) -> list[Task]:
    return await TaskService(session).list(
        user_id=principal.user_id, conversation_id=conversation_id
    )


@router.get("/{task_id}", response_model=Task)
async def get_task(
    task_id: UUID, session: SessionDependency, principal: PrincipalDependency
) -> Task:
    try:
        return await TaskService(session).get(task_id, user_id=principal.user_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到该任务") from exc
