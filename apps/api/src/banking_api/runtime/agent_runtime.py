import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from banking_api.agents.minimal_banking_agent import AgentDefinition
from banking_api.context.builder import ContextBuilder
from banking_api.domain.message import Message
from banking_api.llm.models import LLMMessage
from banking_api.llm.provider import LLMProvider, LLMProviderError
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.tools.executor import ToolExecutor

RuntimeEventSink = Callable[[str, dict[str, Any]], Awaitable[None]]


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
    status: AgentRunStatus = AgentRunStatus.RUNNING


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


class AgentRuntime:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        registry: ToolRegistry,
        executor: ToolExecutor,
        context_builder: ContextBuilder,
        agent: AgentDefinition,
        max_steps: int = 6,
        max_tool_calls: int = 4,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.executor = executor
        self.context_builder = context_builder
        self.agent = agent
        self.max_steps = max_steps
        self.max_tool_calls = max_tool_calls

    async def run(
        self,
        *,
        task_id: UUID,
        conversation_id: UUID,
        current_task: str,
        conversation_messages: list[Message],
        authenticated: bool,
        caller: str | None = None,
        event_sink: RuntimeEventSink | None = None,
    ) -> AgentRunResult:
        state = AgentRunState(task_id=task_id, conversation_id=conversation_id)
        sink = event_sink or self._ignore_event
        effective_caller = caller or self.agent.agent_id
        allowed_tools = self.registry.resolve(self.agent.allowed_capabilities)
        await sink(
            "agent.run.started",
            {
                "agent_id": self.agent.agent_id,
                "max_steps": self.max_steps,
                "max_tool_calls": self.max_tool_calls,
            },
        )
        try:
            while True:
                if state.step_count >= self.max_steps:
                    raise AgentRuntimeError(
                        "AGENT_STEP_LIMIT_EXCEEDED", "Agent step limit exceeded"
                    )
                state.step_count += 1
                request = self.context_builder.build(
                    agent=self.agent,
                    current_task=current_task,
                    conversation_messages=conversation_messages,
                    runtime_messages=state.runtime_messages,
                    allowed_tools=allowed_tools,
                )
                await sink(
                    "llm.request.started",
                    {
                        "step": state.step_count,
                        "message_count": len(request.messages),
                        "tool_names": [tool.name for tool in request.tools],
                    },
                )
                try:
                    response = await self.provider.generate(request)
                except LLMProviderError as exc:
                    raise AgentRuntimeError(
                        "LLM_PROVIDER_ERROR",
                        "LLM provider request failed",
                        category="EXTERNAL",
                        retryable=exc.retryable,
                    ) from exc
                await sink(
                    "llm.request.completed",
                    {
                        "step": state.step_count,
                        "finish_reason": response.finish_reason,
                        "tool_call_count": len(response.tool_calls),
                        "usage": response.usage.model_dump(),
                    },
                )

                if not response.tool_calls:
                    if not response.content:
                        raise AgentRuntimeError(
                            "LLM_INVALID_RESPONSE", "LLM returned neither text nor tool calls"
                        )
                    state.status = AgentRunStatus.COMPLETED
                    await sink(
                        "agent.run.completed",
                        {"steps": state.step_count, "tool_calls": state.tool_call_count},
                    )
                    return AgentRunResult(answer=response.content, state=state)

                state.runtime_messages.append(
                    LLMMessage(
                        role="assistant",
                        content=response.content,
                        tool_calls=response.tool_calls,
                    )
                )
                for call in response.tool_calls:
                    if state.tool_call_count >= self.max_tool_calls:
                        raise AgentRuntimeError(
                            "AGENT_TOOL_CALL_LIMIT_EXCEEDED",
                            "Agent tool-call limit exceeded",
                        )
                    state.tool_call_count += 1
                    argument_keys = (
                        sorted(call.arguments) if isinstance(call.arguments, dict) else []
                    )
                    await sink(
                        "tool.call.started",
                        {
                            "tool_name": call.name,
                            "tool_call_id": call.id,
                            "argument_keys": argument_keys,
                        },
                    )
                    result = await self.executor.execute(
                        tool_name=call.name,
                        arguments=call.arguments,
                        caller=effective_caller,
                        authenticated=authenticated,
                        agent_allowlist=self.agent.allowed_capabilities,
                    )
                    event_type = "tool.call.completed" if result.ok else "tool.call.failed"
                    metadata: dict[str, Any] = {
                        "tool_name": call.name,
                        "tool_call_id": call.id,
                        "capability_id": result.capability_id,
                    }
                    if result.ok:
                        metadata["output_keys"] = sorted(result.output or {})
                        accounts = (result.output or {}).get("accounts")
                        if isinstance(accounts, list):
                            metadata["item_count"] = len(accounts)
                    else:
                        metadata["error_code"] = (
                            result.error.code.value if result.error is not None else None
                        )
                    await sink(event_type, metadata)
                    state.runtime_messages.append(
                        LLMMessage(
                            role="tool",
                            tool_call_id=call.id,
                            content=json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
                        )
                    )
        except AgentRuntimeError as exc:
            state.status = AgentRunStatus.FAILED
            await sink(
                "agent.run.failed",
                {
                    "code": exc.code,
                    "category": exc.category,
                    "retryable": exc.retryable,
                    "steps": state.step_count,
                    "tool_calls": state.tool_call_count,
                },
            )
            raise

    @staticmethod
    async def _ignore_event(_: str, __: dict[str, Any]) -> None:
        return None
