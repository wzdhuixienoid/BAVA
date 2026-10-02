import json
from typing import Any

from banking_api.agents.minimal_banking_agent import AgentDefinition
from banking_api.context.builder import ContextBuilder
from banking_api.llm.models import LLMMessage
from banking_api.llm.provider import LLMProvider, LLMProviderError
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.runtime.base import (
    AgentRunRequest,
    AgentRunResult,
    AgentRunState,
    AgentRunStatus,
    AgentRuntimeError,
    SuccessfulToolResult,
    ignore_runtime_event,
)
from banking_api.tools.executor import ToolExecutor
from banking_api.tools.models import ToolErrorDisposition


class ManualAgentRuntime:
    """Reference implementation of the project-owned agent loop."""

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

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        state = AgentRunState(task_id=request.task_id, conversation_id=request.conversation_id)
        sink = request.event_sink or ignore_runtime_event
        effective_caller = request.caller or self.agent.agent_id
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
                llm_request = self.context_builder.build(
                    agent=self.agent,
                    current_task=request.current_task,
                    conversation_messages=request.conversation_messages,
                    runtime_messages=state.runtime_messages,
                    allowed_tools=allowed_tools,
                )
                await sink(
                    "llm.request.started",
                    {
                        "step": state.step_count,
                        "message_count": len(llm_request.messages),
                        "tool_names": [tool.name for tool in llm_request.tools],
                    },
                )
                try:
                    response = await self.provider.generate(llm_request)
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
                        principal=request.principal,
                        agent_allowlist=self.agent.allowed_capabilities,
                    )
                    event_type = "tool.call.completed" if result.ok else "tool.call.failed"
                    metadata: dict[str, Any] = {
                        "tool_name": call.name,
                        "tool_call_id": call.id,
                        "capability_id": result.capability_id,
                    }
                    if result.ok:
                        state.successful_tool_results.append(
                            SuccessfulToolResult(
                                capability_id=result.capability_id,
                                tool_name=call.name,
                                arguments=call.arguments,
                                output=result.output or {},
                            )
                        )
                        metadata["output_keys"] = sorted(result.output or {})
                        accounts = (result.output or {}).get("accounts")
                        if isinstance(accounts, list):
                            metadata["item_count"] = len(accounts)
                    else:
                        metadata["error_code"] = (
                            result.error.code.value if result.error is not None else None
                        )
                    await sink(event_type, metadata)
                    if (
                        result.error is not None
                        and result.error.disposition is ToolErrorDisposition.FATAL
                    ):
                        raise AgentRuntimeError(
                            result.error.code.value,
                            result.error.message,
                            category="TOOL",
                            retryable=result.error.retryable,
                        )
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
