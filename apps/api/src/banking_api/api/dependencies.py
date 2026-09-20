from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.persistence.database import get_session
from banking_api.runtime.event_bus import EventBus
from banking_api.runtime.task_runner import InProcessTaskRunner


@dataclass(frozen=True)
class DevPrincipal:
    user_id: str


def get_current_principal() -> DevPrincipal:
    return DevPrincipal(user_id="dev-user-001")


def get_event_bus(request: Request) -> EventBus:
    return request.app.state.event_bus


def get_task_runner(request: Request) -> InProcessTaskRunner:
    return request.app.state.task_runner


SessionDependency = Annotated[AsyncSession, Depends(get_session, scope="function")]
PrincipalDependency = Annotated[DevPrincipal, Depends(get_current_principal)]
EventBusDependency = Annotated[EventBus, Depends(get_event_bus)]
TaskRunnerDependency = Annotated[InProcessTaskRunner, Depends(get_task_runner)]
