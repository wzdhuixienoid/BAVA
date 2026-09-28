from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.domain.principal import Principal
from banking_api.persistence.database import get_session
from banking_api.runtime.event_bus import EventBus
from banking_api.runtime.task_runner import InProcessTaskRunner
from banking_api.workflows.transfer.engine import TransferWorkflowEngine

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_principal(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
    credential: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> Principal:
    from banking_api.security.authentication import (
        AuthenticationError,
        IdentityNotProvisionedError,
    )

    token = credential.credentials if credential is not None else None
    try:
        return await request.app.state.authentication_service.authenticate(
            bearer_token=token,
            session=session,
        )
    except IdentityNotProvisionedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "IDENTITY_NOT_PROVISIONED",
                "message": "Authenticated identity is not provisioned",
            },
        ) from exc
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": exc.code, "message": "Authentication failed"},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_event_bus(request: Request) -> EventBus:
    return request.app.state.event_bus


def get_task_runner(request: Request) -> InProcessTaskRunner:
    return request.app.state.task_runner


def get_transfer_workflow_engine(request: Request) -> TransferWorkflowEngine:
    return request.app.state.transfer_workflow_engine


SessionDependency = Annotated[AsyncSession, Depends(get_session, scope="function")]
PrincipalDependency = Annotated[Principal, Depends(get_current_principal)]
EventBusDependency = Annotated[EventBus, Depends(get_event_bus)]
TaskRunnerDependency = Annotated[InProcessTaskRunner, Depends(get_task_runner)]
TransferWorkflowEngineDependency = Annotated[
    TransferWorkflowEngine, Depends(get_transfer_workflow_engine)
]
