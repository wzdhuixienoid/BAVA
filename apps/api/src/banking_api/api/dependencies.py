from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.application.bootstrap_runtime import BootstrapRuntime
from banking_api.persistence.database import get_session
from banking_api.runtime.event_bus import EventBus


@dataclass(frozen=True)
class DevPrincipal:
    user_id: str


def get_current_principal() -> DevPrincipal:
    return DevPrincipal(user_id="dev-user-001")


def get_event_bus(request: Request) -> EventBus:
    return request.app.state.event_bus


def get_bootstrap_runtime(request: Request) -> BootstrapRuntime:
    return request.app.state.bootstrap_runtime


SessionDependency = Annotated[AsyncSession, Depends(get_session, scope="function")]
PrincipalDependency = Annotated[DevPrincipal, Depends(get_current_principal)]
EventBusDependency = Annotated[EventBus, Depends(get_event_bus)]
BootstrapRuntimeDependency = Annotated[BootstrapRuntime, Depends(get_bootstrap_runtime)]
