from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from banking_api.agents.personal_banking_agent import PERSONAL_BANKING_ACCOUNT_AGENT
from banking_api.context.builder import ContextBuilder
from banking_api.domain.enums import MessageRole, RiskLevel
from banking_api.domain.message import Message
from banking_api.domain.principal import ExecutionPrincipal
from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.llm.models import LLMResponse, LLMToolCall
from banking_api.llm.provider import LLMProviderError
from banking_api.mock_bank.service import MockBankService
from banking_api.policy.service import PolicyService
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.runtime.base import AgentRunRequest, AgentRuntime, AgentRuntimeError
from banking_api.runtime.langgraph.graph import LangGraphAgentRuntime
from banking_api.runtime.manual_agent_runtime import ManualAgentRuntime
from banking_api.tools.banking import build_get_balance_tool, build_list_accounts_tool
from banking_api.tools.executor import ToolExecutor
from banking_api.tools.models import ListAccountsInput, ListAccountsOutput, ToolSpec

Backend = Literal["manual", "langgraph"]


def build_runtime(
    backend: Backend,
    responses: list[LLMResponse | Exception],
    *,
    max_steps: int = 6,
    max_tool_calls: int = 4,
    invalid_list_output: bool = False,
) -> tuple[AgentRuntime, FakeLLMProvider]:
    provider = FakeLLMProvider(responses)
    registry = ToolRegistry()
    bank = MockBankService()
    if invalid_list_output:
        registry.register(
            ToolSpec(
                capability_id="account.list",
                name="list_accounts",
                description="invalid output test double",
                input_model=ListAccountsInput,
                output_model=ListAccountsOutput,
                risk_level=RiskLevel.R1_PRIVATE_READ,
                side_effect=False,
                allowed_callers=frozenset({"agent:personal-banking"}),
                handler=lambda _context, _arguments: {"accounts": "not-a-list"},
            )
        )
    else:
        registry.register(build_list_accounts_tool(bank))
    registry.register(build_get_balance_tool(bank))
    common = {
        "provider": provider,
        "registry": registry,
        "executor": ToolExecutor(registry, PolicyService()),
        "context_builder": ContextBuilder(),
        "agent": PERSONAL_BANKING_ACCOUNT_AGENT,
        "max_steps": max_steps,
        "max_tool_calls": max_tool_calls,
    }
    runtime: AgentRuntime
    if backend == "manual":
        runtime = ManualAgentRuntime(**common)
    else:
        runtime = LangGraphAgentRuntime(checkpointer=InMemorySaver(), **common)
    return runtime, provider


def request(content: str = "我有哪些账户？", *, caller: str | None = None) -> AgentRunRequest:
    conversation_id = uuid4()
    message = Message(
        message_id=uuid4(),
        conversation_id=conversation_id,
        role=MessageRole.USER,
        content=content,
        created_at=datetime.now(UTC),
    )
    return AgentRunRequest(
        task_id=uuid4(),
        conversation_id=conversation_id,
        current_task=content,
        conversation_messages=[message],
        principal=ExecutionPrincipal.for_task("dev-user-001"),
        caller=caller,
    )


@pytest.mark.parametrize("backend", ["manual", "langgraph"])
async def test_direct_final_parity(backend: Backend) -> None:
    runtime, _ = build_runtime(backend, [LLMResponse(content="你好")])
    result = await runtime.run(request())
    assert (result.answer, result.state.step_count, result.state.tool_call_count) == (
        "你好",
        1,
        0,
    )


@pytest.mark.parametrize("backend", ["manual", "langgraph"])
async def test_list_accounts_parity(backend: Backend) -> None:
    runtime, provider = build_runtime(
        backend,
        [
            LLMResponse(tool_calls=[LLMToolCall(id="list", name="list_accounts", arguments={})]),
            LLMResponse(content="你有 4 个账户。"),
        ],
    )
    result = await runtime.run(request())
    assert result.answer == "你有 4 个账户。"
    assert result.state.tool_call_count == 1
    assert "acc_salary" in (provider.requests[1].messages[-1].content or "")


@pytest.mark.parametrize("backend", ["manual", "langgraph"])
async def test_multi_tool_parity(backend: Backend) -> None:
    runtime, _ = build_runtime(
        backend,
        [
            LLMResponse(tool_calls=[LLMToolCall(id="list", name="list_accounts", arguments={})]),
            LLMResponse(
                tool_calls=[
                    LLMToolCall(
                        id="balance",
                        name="get_balance",
                        arguments={"account_id": "acc_salary"},
                    )
                ]
            ),
            LLMResponse(content="工资卡余额为 23,864.52 元。"),
        ],
    )
    result = await runtime.run(request("我的工资卡余额是多少？"))
    assert result.answer == "工资卡余额为 23,864.52 元。"
    assert (result.state.step_count, result.state.tool_call_count) == (3, 2)


@pytest.mark.parametrize("backend", ["manual", "langgraph"])
async def test_invalid_argument_can_be_repaired(backend: Backend) -> None:
    runtime, provider = build_runtime(
        backend,
        [
            LLMResponse(
                tool_calls=[LLMToolCall(id="bad", name="get_balance", arguments={"wrong": "value"})]
            ),
            LLMResponse(
                tool_calls=[
                    LLMToolCall(
                        id="fixed",
                        name="get_balance",
                        arguments={"account_id": "acc_salary"},
                    )
                ]
            ),
            LLMResponse(content="已修正。"),
        ],
    )
    result = await runtime.run(request())
    assert result.answer == "已修正。"
    assert "TOOL_ARGUMENT_VALIDATION_FAILED" in (provider.requests[1].messages[-1].content or "")


@pytest.mark.parametrize("backend", ["manual", "langgraph"])
async def test_policy_denial_is_fatal(backend: Backend) -> None:
    runtime, provider = build_runtime(
        backend,
        [
            LLMResponse(tool_calls=[LLMToolCall(id="denied", name="list_accounts", arguments={})]),
            LLMResponse(content="must not be reached"),
        ],
    )
    with pytest.raises(AgentRuntimeError) as caught:
        await runtime.run(request(caller="agent:unknown"))
    assert caught.value.code == "TOOL_NOT_ALLOWED"
    assert provider.requests == []  # Caller impersonation is rejected before model/tool execution.


@pytest.mark.parametrize("backend", ["manual", "langgraph"])
async def test_unknown_write_tool_is_fatal(backend: Backend) -> None:
    runtime, provider = build_runtime(
        backend,
        [
            LLMResponse(
                tool_calls=[
                    LLMToolCall(
                        id="write",
                        name="execute_transfer",
                        arguments={"payee": "张三", "amount": 10000},
                    )
                ]
            ),
            LLMResponse(content="must not be reached"),
        ],
    )
    with pytest.raises(AgentRuntimeError) as caught:
        await runtime.run(request())
    assert caught.value.code == "TOOL_NOT_FOUND"
    assert len(provider.requests) == 1


@pytest.mark.parametrize("backend", ["manual", "langgraph"])
async def test_output_validation_failure_is_fatal(backend: Backend) -> None:
    runtime, provider = build_runtime(
        backend,
        [
            LLMResponse(tool_calls=[LLMToolCall(id="invalid", name="list_accounts", arguments={})]),
            LLMResponse(content="must not be reached"),
        ],
        invalid_list_output=True,
    )
    with pytest.raises(AgentRuntimeError) as caught:
        await runtime.run(request())
    assert caught.value.code == "TOOL_OUTPUT_VALIDATION_FAILED"
    assert len(provider.requests) == 1


@pytest.mark.parametrize("backend", ["manual", "langgraph"])
async def test_provider_failure_parity(backend: Backend) -> None:
    runtime, _ = build_runtime(backend, [LLMProviderError("network")])
    with pytest.raises(AgentRuntimeError) as caught:
        await runtime.run(request())
    assert caught.value.as_dict()["code"] == "LLM_PROVIDER_ERROR"
    assert caught.value.as_dict()["category"] == "EXTERNAL"


@pytest.mark.parametrize("backend", ["manual", "langgraph"])
async def test_step_limit_parity(backend: Backend) -> None:
    repeated = LLMResponse(tool_calls=[LLMToolCall(id="loop", name="list_accounts", arguments={})])
    runtime, _ = build_runtime(backend, [repeated, repeated], max_steps=2, max_tool_calls=10)
    with pytest.raises(AgentRuntimeError) as caught:
        await runtime.run(request())
    assert caught.value.code == "AGENT_STEP_LIMIT_EXCEEDED"


@pytest.mark.parametrize("backend", ["manual", "langgraph"])
async def test_tool_call_limit_parity(backend: Backend) -> None:
    runtime, _ = build_runtime(
        backend,
        [
            LLMResponse(
                tool_calls=[
                    LLMToolCall(id="one", name="list_accounts", arguments={}),
                    LLMToolCall(id="two", name="list_accounts", arguments={}),
                ]
            )
        ],
        max_tool_calls=1,
    )
    with pytest.raises(AgentRuntimeError) as caught:
        await runtime.run(request())
    assert caught.value.code == "AGENT_TOOL_CALL_LIMIT_EXCEEDED"
