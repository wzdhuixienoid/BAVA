import json
from typing import Any, Literal, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from banking_api.agents.models import AgentDefinition
from banking_api.agents.personal_banking_agent import uses_financial_analysis
from banking_api.config.demo_time import reference_now
from banking_api.context.builder import ContextBuilder
from banking_api.domain.statement_scope import statement_arguments
from banking_api.financial.request_scope import (
    anomaly_requested,
    declines_anomaly_review,
    request_scope,
    restrict_financial_agent,
)
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
from banking_api.tools.models import ToolErrorCode, ToolErrorDisposition


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
        max_tool_calls: int = 8,
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
        if request.caller is not None and request.caller != agent.agent_id:
            raise AgentRuntimeError("TOOL_NOT_ALLOWED", "Agent cannot impersonate another caller")
        await sink(
            "agent.run.started",
            {
                "agent_id": agent.agent_id,
                "skills": [skill.metadata() for skill in agent.skills],
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
            scope = (
                request_scope(
                    request.current_task,
                    reference_now(),
                    include_calendar=anomaly_requested(request.current_task),
                )
                if uses_financial_analysis(agent)
                else None
            )
            if scope and scope.window and anomaly_requested(request.current_task):
                from banking_api.financial.anomaly_models import TransactionAnomalyInput
                from banking_api.financial.errors import FinancialDomainError

                try:
                    TransactionAnomalyInput.model_validate(scope.window).bounds(reference_now())
                except FinancialDomainError as exc:
                    from banking_api.financial.request_scope import FinancialRequestScope

                    scope = FinancialRequestScope(clarification=exc.message)
            initial = {
                "task_id": str(request.task_id),
                "conversation_id": str(request.conversation_id),
                "agent_id": agent.agent_id,
                "skills": [skill.metadata() for skill in agent.skills],
                "runtime_messages": [
                    LLMMessage(
                        role="assistant",
                        tool_calls=list(request.initial_tool_calls),
                        reasoning_content="",
                    ).model_dump(mode="json")
                ]
                if request.initial_tool_calls
                else [],
                "step_count": 0,
                "tool_call_count": 0,
                "pending_tool_calls": [
                    c.model_dump(mode="json") for c in request.initial_tool_calls
                ],
                "successful_tool_results": [],
                "financial_window": scope.window if scope else None,
                "financial_clarification": scope.clarification if scope else None,
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
            if state.get("financial_clarification"):
                return {"final_answer": state["financial_clarification"]}
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
                wealth_context=request.wealth_context,
                statement_context=request.statement_context,
            )
            if state.get("financial_window"):
                window = state["financial_window"]
                llm_request.messages.append(
                    LLMMessage(
                        role="system",
                        content=(
                            f"本次用户明确要求的消费区间为 {window['start_at']} "
                            f"至 {window['end_at']}。"
                            "所有消费工具必须使用该起止时间；这优先于默认自然月。工具执行层会固定此区间。"
                            "请将起止时间按北京时间用中文说明，不得切换月份。"
                        ),
                    )
                )
            if uses_financial_analysis(agent) and state["tool_call_count"] >= self.max_tool_calls:
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
                reasoning_content=response.reasoning_content,
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
                spec = self.registry.get_by_name(call.name)
                arguments = call.arguments
                if spec and spec.capability_id == "account.statement":
                    arguments = statement_arguments(
                        arguments, request.current_task, continuation=request.statement_context
                    )
                if (
                    spec
                    and spec.capability_id == "transaction.spending_summary"
                    and isinstance(arguments, dict)
                ):
                    # The user controls opting out; the model cannot disable the default check.
                    arguments = dict(arguments)
                    arguments.pop("include_review", None)
                    if declines_anomaly_review(request.current_task):
                        arguments["include_review"] = False
                if (
                    state.get("financial_window")
                    and spec
                    and spec.capability_id
                    in {
                        "transaction.spending_summary",
                        "transaction.category_breakdown",
                        "transaction.top_transactions",
                        "transaction.compare_periods",
                        "transaction.detect_anomalies",
                    }
                    and isinstance(arguments, dict)
                ):
                    arguments = {
                        key: value
                        for key, value in arguments.items()
                        if key
                        not in {"month", "recent_days", "analysis_days", "start_at", "end_at"}
                    } | state["financial_window"]
                if (
                    uses_financial_analysis(agent)
                    and spec
                    and spec.capability_id == "transaction.detect_anomalies"
                    and spec.capability_id not in agent.allowed_capabilities
                ):
                    result = self.executor._error(
                        ToolErrorCode.TOOL_ARGUMENT_VALIDATION_FAILED,
                        "用户没有要求异常交易分析。请按用户指定期间分析普通消费；无法分析时说明所缺信息。",
                        capability_id=spec.capability_id,
                    )
                else:
                    result = await self.executor.execute(
                        tool_name=call.name,
                        arguments=arguments,
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
                        spec.input_model.model_validate(arguments).model_dump(
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
        builder.add_edge(START, "tool" if request.initial_tool_calls else "llm")
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
        from banking_api.financial.anomaly_models import TransactionAnomalySnapshot
        from banking_api.skills.transaction_anomaly_analysis import TransactionAnomalyAnalysisSkill

        anomaly = next(
            (
                item
                for item in state.successful_tool_results
                if item.capability_id == "transaction.detect_anomalies"
            ),
            None,
        )
        if anomaly is not None:
            snapshot = TransactionAnomalySnapshot.model_validate(anomaly.output["snapshot"])
            skill = TransactionAnomalyAnalysisSkill()
            metadata = {
                "skill_id": skill.definition.skill_id,
                "skill_version": skill.definition.version,
                "skill_package": skill.active_skill.metadata(),
            }
            await sink("skill.run.started", metadata)
            detailed_answer = skill.execute(snapshot).answer
            if any(
                item.capability_id == "transaction.spending_summary"
                for item in state.successful_tool_results
            ):
                graph_state["final_answer"] += "\n\n" + detailed_answer
            else:
                from banking_api.application.account_results import account_query_answer

                account_answer = (
                    account_query_answer(state.successful_tool_results)
                    if any(
                        s.skill_id == "banking-assistance"
                        for s in self._resolve_agent(request).skills
                    )
                    else ""
                )
                graph_state["final_answer"] = (
                    account_answer + "\n\n" if account_answer else ""
                ) + detailed_answer
            await sink("skill.run.completed", metadata)
        elif uses_financial_analysis(self._resolve_agent(request)):
            review = next(
                (
                    item.output.get("spending_review")
                    for item in state.successful_tool_results
                    if item.capability_id == "transaction.spending_summary"
                ),
                None,
            )
            if review:
                metadata = {
                    "skill_id": "skill:transaction-anomaly-analysis",
                    "skill_version": 1,
                    "presentation": "brief",
                    "skill_package": TransactionAnomalyAnalysisSkill().active_skill.metadata(),
                }
                await sink("skill.run.started", metadata)
                graph_state["final_answer"] += "\n\n" + review["answer"]
                await sink("skill.run.completed", metadata)
        state.status = AgentRunStatus.COMPLETED
        await sink(
            "agent.run.completed",
            {"steps": state.step_count, "tool_calls": state.tool_call_count},
        )
        from banking_api.runtime.grounding import ground_read_answer

        return AgentRunResult(
            answer=graph_state["financial_clarification"]
            if graph_state.get("financial_clarification")
            else ground_read_answer(
                self._resolve_agent(request),
                request.current_task,
                graph_state["final_answer"],
                state.successful_tool_results,
            ),
            state=state,
        )

    def _resolve_agent(self, request: AgentRunRequest) -> AgentDefinition:
        agent = request.agent or self.agent
        if agent is None:
            raise AgentRuntimeError(
                "AGENT_NOT_SELECTED",
                "LangGraph runtime requires an AgentDefinition",
            )
        try:
            agent.validate_skills()
        except ValueError as exc:
            raise AgentRuntimeError(
                "AGENT_SKILL_BINDING_INVALID", "Agent requires a valid standard skill binding"
            ) from exc
        return restrict_financial_agent(agent, request.current_task)

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
