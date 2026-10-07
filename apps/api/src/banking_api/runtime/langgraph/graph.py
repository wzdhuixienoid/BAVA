import json
from typing import Any, Literal, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from banking_api.agents.models import AgentDefinition
from banking_api.context.builder import ContextBuilder
from banking_api.llm.models import LLMMessage, LLMToolCall
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
from banking_api.runtime.langgraph.state import BankingAgentGraphState
from banking_api.tools.executor import ToolExecutor
from banking_api.tools.models import ToolErrorDisposition


class LangGraphAgentRuntime:
    """Direct StateGraph orchestration over the project's existing provider and tools."""

    checkpoint_enabled = True

    def __init__(
        self,
        *,
        provider: LLMProvider,
        registry: ToolRegistry,
        executor: ToolExecutor,
        context_builder: ContextBuilder,
        agent: AgentDefinition | None = None,
        checkpointer: BaseCheckpointSaver,
        max_steps: int = 6,
        max_tool_calls: int = 4,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.executor = executor
        self.context_builder = context_builder
        self.agent = agent
        self.checkpointer = checkpointer
        self.max_steps = max_steps
        self.max_tool_calls = max_tool_calls

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        state = await self._invoke(request, resume=False, interrupt_after_tool=False)
        return await self._finish(request, state)

    async def run_until_tool_checkpoint(self, request: AgentRunRequest) -> BankingAgentGraphState:
        """Controlled durability experiment hook; not exposed through the product API."""
        return await self._invoke(request, resume=False, interrupt_after_tool=True)

    async def resume(self, request: AgentRunRequest) -> AgentRunResult:
        state = await self._invoke(request, resume=True, interrupt_after_tool=False)
        return await self._finish(request, state)

    async def _invoke(
        self,
        request: AgentRunRequest,
        *,
        resume: bool,
        interrupt_after_tool: bool,
    ) -> BankingAgentGraphState:
        sink = request.event_sink or ignore_runtime_event
        agent = self._resolve_agent(request)
        await sink(
            "agent.run.started",
            {
                "agent_id": agent.agent_id,
                "max_steps": self.max_steps,
                "max_tool_calls": self.max_tool_calls,
            },
        )
        graph = self._build_graph(
            request,
            agent=agent,
            interrupt_after_tool=interrupt_after_tool,
        )
        config = {"configurable": {"thread_id": str(request.task_id)}}
        initial: BankingAgentGraphState | None
        if resume:
            initial = None
        else:
            initial = {
                "task_id": str(request.task_id),
                "conversation_id": str(request.conversation_id),
                "agent_id": agent.agent_id,
                "runtime_messages": [],
                "step_count": 0,
                "tool_call_count": 0,
                "pending_tool_calls": [],
                "successful_tool_results": [],
                "final_answer": None,
                "error": None,
            }
        result = await graph.ainvoke(initial, config=config)
        return cast(BankingAgentGraphState, result)

    def _build_graph(
        self,
        request: AgentRunRequest,
        *,
        agent: AgentDefinition,
        interrupt_after_tool: bool,
    ):
        sink = request.event_sink or ignore_runtime_event
        allowed_tools = self.registry.resolve(agent.allowed_capabilities)
        effective_caller = request.caller or agent.agent_id

        async def llm_node(state: BankingAgentGraphState) -> dict[str, Any]:
            if state["step_count"] >= self.max_steps:
                return {
                    "error": self._error("AGENT_STEP_LIMIT_EXCEEDED", "Agent step limit exceeded")
                }
            step_count = state["step_count"] + 1
            runtime_messages = [
                LLMMessage.model_validate(item) for item in state["runtime_messages"]
            ]
            llm_request = self.context_builder.build(
                agent=agent,
                current_task=request.current_task,
                conversation_messages=request.conversation_messages,
                runtime_messages=runtime_messages,
                allowed_tools=allowed_tools,
            )
            if (
                agent.agent_id == "agent:financial-analysis"
                and state["tool_call_count"] >= self.max_tool_calls
            ):
                llm_request = llm_request.model_copy(update={"tools": []})
                llm_request.messages.append(
                    LLMMessage(
                        role="system",
                        content="工具预算已用完。请依据成功结果回答；没有数据则说明无法分析该期间。禁止继续调用工具。",
                    )
                )
            await sink(
                "llm.request.started",
                {
                    "step": step_count,
                    "message_count": len(llm_request.messages),
                    "tool_names": [tool.name for tool in llm_request.tools],
                },
            )
            try:
                response = await self.provider.generate(llm_request)
            except LLMProviderError as exc:
                return {
                    "step_count": step_count,
                    "error": self._error(
                        "LLM_PROVIDER_ERROR",
                        "LLM provider request failed",
                        category="EXTERNAL",
                        retryable=exc.retryable,
                    ),
                }
            await sink(
                "llm.request.completed",
                {
                    "step": step_count,
                    "finish_reason": response.finish_reason,
                    "tool_call_count": len(response.tool_calls),
                    "usage": response.usage.model_dump(),
                },
            )
            if not response.tool_calls:
                if not response.content:
                    return {
                        "step_count": step_count,
                        "error": self._error(
                            "LLM_INVALID_RESPONSE", "LLM returned neither text nor tool calls"
                        ),
                    }
                return {
                    "step_count": step_count,
                    "pending_tool_calls": [],
                    "final_answer": response.content,
                }
            assistant = LLMMessage(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            )
            return {
                "step_count": step_count,
                "runtime_messages": [*state["runtime_messages"], assistant.model_dump(mode="json")],
                "pending_tool_calls": [
                    call.model_dump(mode="json") for call in response.tool_calls
                ],
                "final_answer": None,
            }

        async def tool_node(state: BankingAgentGraphState) -> dict[str, Any]:
            messages = list(state["runtime_messages"])
            tool_call_count = state["tool_call_count"]
            successful_tool_results = list(state["successful_tool_results"])
            for raw_call in state["pending_tool_calls"]:
                call = LLMToolCall.model_validate(raw_call)
                if tool_call_count >= self.max_tool_calls:
                    return {
                        "tool_call_count": tool_call_count,
                        "pending_tool_calls": [],
                        "error": self._error(
                            "AGENT_TOOL_CALL_LIMIT_EXCEEDED",
                            "Agent tool-call limit exceeded",
                        ),
                    }
                tool_call_count += 1
                argument_keys = sorted(call.arguments) if isinstance(call.arguments, dict) else []
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
                    agent_allowlist=agent.allowed_capabilities,
                )
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
                    await sink("tool.call.completed", metadata)
                    spec = self.registry.get_by_name(call.name)
                    sanitized_arguments = (
                        spec.input_model.model_validate(call.arguments).model_dump(
                            mode="json", exclude_none=True
                        )
                        if spec is not None
                        else {}
                    )
                    successful_tool_results.append(
                        SuccessfulToolResult(
                            capability_id=result.capability_id or "",
                            tool_name=call.name,
                            arguments=sanitized_arguments,
                            output=dict(result.output or {}),
                        ).model_dump(mode="json")
                    )
                else:
                    metadata["error_code"] = (
                        result.error.code.value if result.error is not None else None
                    )
                    await sink("tool.call.failed", metadata)
                    if (
                        result.error is not None
                        and result.error.disposition is ToolErrorDisposition.FATAL
                    ):
                        return {
                            "tool_call_count": tool_call_count,
                            "pending_tool_calls": [],
                            "error": self._error(
                                result.error.code.value,
                                result.error.message,
                                category="TOOL",
                                retryable=result.error.retryable,
                            ),
                        }
                messages.append(
                    LLMMessage(
                        role="tool",
                        tool_call_id=call.id,
                        content=json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
                    ).model_dump(mode="json")
                )
            return {
                "runtime_messages": messages,
                "tool_call_count": tool_call_count,
                "pending_tool_calls": [],
                "successful_tool_results": successful_tool_results,
            }

        def after_llm(
            state: BankingAgentGraphState,
        ) -> Literal["tool", "end"]:
            if state["error"] is not None or state["final_answer"] is not None:
                return "end"
            if state["pending_tool_calls"]:
                return "tool"
            return "end"

        def after_tool(state: BankingAgentGraphState) -> Literal["llm", "end"]:
            return "end" if state["error"] is not None else "llm"

        builder = StateGraph(BankingAgentGraphState)
        builder.add_node("llm", llm_node)
        builder.add_node("tool", tool_node)
        builder.add_edge(START, "llm")
        builder.add_conditional_edges("llm", after_llm, {"tool": "tool", "end": END})
        builder.add_conditional_edges("tool", after_tool, {"llm": "llm", "end": END})
        return builder.compile(
            checkpointer=self.checkpointer,
            interrupt_after=["tool"] if interrupt_after_tool else None,
            name="banking-specialist-agent",
        )

    async def _finish(
        self, request: AgentRunRequest, graph_state: BankingAgentGraphState
    ) -> AgentRunResult:
        sink = request.event_sink or ignore_runtime_event
        state = AgentRunState(
            task_id=request.task_id,
            conversation_id=request.conversation_id,
            step_count=graph_state["step_count"],
            tool_call_count=graph_state["tool_call_count"],
            runtime_messages=[
                LLMMessage.model_validate(item) for item in graph_state["runtime_messages"]
            ],
            successful_tool_results=[
                SuccessfulToolResult.model_validate(item)
                for item in graph_state["successful_tool_results"]
            ],
        )
        if graph_state["error"] is not None:
            state.status = AgentRunStatus.FAILED
            error = graph_state["error"]
            await sink(
                "agent.run.failed",
                {
                    "code": error["code"],
                    "category": error["category"],
                    "retryable": error["retryable"],
                    "steps": state.step_count,
                    "tool_calls": state.tool_call_count,
                },
            )
            raise AgentRuntimeError(
                error["code"],
                error["message"],
                category=error["category"],
                retryable=error["retryable"],
            )
        if graph_state["final_answer"] is None:
            raise AgentRuntimeError(
                "AGENT_GRAPH_INCOMPLETE", "LangGraph run ended without a final answer"
            )
        state.status = AgentRunStatus.COMPLETED
        await sink(
            "agent.run.completed",
            {"steps": state.step_count, "tool_calls": state.tool_call_count},
        )
        return AgentRunResult(answer=graph_state["final_answer"], state=state)

    def _resolve_agent(self, request: AgentRunRequest) -> AgentDefinition:
        agent = request.agent or self.agent
        if agent is None:
            raise AgentRuntimeError(
                "AGENT_NOT_SELECTED",
                "LangGraph runtime requires an AgentDefinition",
            )
        return agent

    @staticmethod
    def _error(
        code: str,
        message: str,
        *,
        category: str = "INTERNAL",
        retryable: bool = False,
    ) -> dict[str, Any]:
        return {
            "category": category,
            "code": code,
            "message": message,
            "retryable": retryable,
        }
