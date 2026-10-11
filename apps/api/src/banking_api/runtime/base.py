from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from banking_api.agents.models import AgentDefinition
from banking_api.domain.message import Message
from banking_api.domain.principal import ExecutionPrincipal
from banking_api.llm.models import LLMMessage

RuntimeEventSink = Callable[[str, dict[str, Any]], Awaitable[None]]


class SuccessfulToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)


class AgentRunStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class AgentRunState:
    task_id: UUID
    conversation_id: UUID
    step_count: int = 0
    tool_call_count: int = 0
    runtime_messages: list[LLMMessage] = field(default_factory=list)
    successful_tool_results: list[SuccessfulToolResult] = field(default_factory=list)
    status: AgentRunStatus = AgentRunStatus.RUNNING


@dataclass(frozen=True)
class AgentRunRequest:
    task_id: UUID
    conversation_id: UUID
    current_task: str
    conversation_messages: list[Message]
    principal: ExecutionPrincipal
    agent: AgentDefinition | None = None
    caller: str | None = None
    event_sink: RuntimeEventSink | None = None
    wealth_context: dict[str, Any] | None = None


@dataclass(frozen=True)
class AgentRunResult:
    answer: str
    state: AgentRunState


class AgentRuntimeError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        category: str = "INTERNAL",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.category = category
        self.retryable = retryable

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "code": self.code,
            "message": str(self),
            "retryable": self.retryable,
        }


class AgentRuntime(Protocol):
    async def run(self, request: AgentRunRequest) -> AgentRunResult: ...


async def ignore_runtime_event(_: str, __: dict[str, Any]) -> None:
    return None
