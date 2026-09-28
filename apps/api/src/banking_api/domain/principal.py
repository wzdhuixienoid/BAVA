from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True, slots=True)
class Principal:
    """Authenticated request identity mapped to a stable application user."""

    user_id: str
    issuer: str
    subject: str
    auth_time: datetime | None = None
    amr: tuple[str, ...] = ()
    acr: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionPrincipal:
    """Server-created authority used after the HTTP credential has gone away."""

    user_id: str
    source: Literal["authenticated_request", "durable_task", "workflow", "recovery"]

    @classmethod
    def from_request(cls, principal: Principal) -> "ExecutionPrincipal":
        return cls(user_id=principal.user_id, source="authenticated_request")

    @classmethod
    def for_task(cls, user_id: str) -> "ExecutionPrincipal":
        return cls(user_id=user_id, source="durable_task")

    @classmethod
    def for_workflow(cls, user_id: str) -> "ExecutionPrincipal":
        return cls(user_id=user_id, source="workflow")

    @classmethod
    def for_recovery(cls, user_id: str) -> "ExecutionPrincipal":
        return cls(user_id=user_id, source="recovery")
