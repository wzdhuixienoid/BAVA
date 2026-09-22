from datetime import UTC, datetime
from uuid import uuid4

import pytest

from banking_api.agents.minimal_banking_agent import MINIMAL_BANKING_AGENT
from banking_api.context.builder import ContextBuilder
from banking_api.domain.enums import MessageRole
from banking_api.domain.message import Message
from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.llm.models import LLMResponse, LLMToolCall
from banking_api.llm.provider import LLMProviderError
from banking_api.mock_bank.service import MockBankService
from banking_api.policy.service import PolicyService
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.runtime.agent_runtime import (
    AgentRunRequest,
    AgentRuntime,
    AgentRuntimeError,
)
from banking_api.tools.banking import build_get_balance_tool, build_list_accounts_tool
from banking_api.tools.executor import ToolExecutor


def build_runtime(
    responses: list[LLMResponse | Exception], *, max_steps: int = 6, max_tool_calls: int = 4
) -> tuple[AgentRuntime, FakeLLMProvider]:
    provider = FakeLLMProvider(responses)
    registry = ToolRegistry()
    bank = MockBankService()
    registry.register(build_list_accounts_tool(bank))
    registry.register(build_get_balance_tool(bank))
    runtime = AgentRuntime(
        provider=provider,
        registry=registry,
        executor=ToolExecutor(registry, PolicyService()),
        context_builder=ContextBuilder(),
        agent=MINIMAL_BANKING_AGENT,
        max_steps=max_steps,
        max_tool_calls=max_tool_calls,
    )
    return runtime, provider


def user_message(content: str) -> Message:
    return Message(
        message_id=uuid4(),
        conversation_id=uuid4(),
        role=MessageRole.USER,
        content=content,
        created_at=datetime.now(UTC),
    )


async def run_runtime(
    runtime: AgentRuntime,
    content: str = "我有哪些账户？",
    *,
    caller: str | None = None,
) -> tuple[object, list[tuple[str, dict[str, object]]]]:
    events: list[tuple[str, dict[str, object]]] = []

    async def sink(event_type, data):  # type: ignore[no-untyped-def]
        events.append((event_type, data))

    message = user_message(content)
    result = await runtime.run(
        AgentRunRequest(
            task_id=uuid4(),
            conversation_id=message.conversation_id,
            current_task=content,
            conversation_messages=[message],
            authenticated=True,
            caller=caller,
            event_sink=sink,
        )
    )
    return result, events


async def test_llm_direct_answer() -> None:
    runtime, provider = build_runtime([LLMResponse(content="你好")])

    result, events = await run_runtime(runtime)

    assert result.answer == "你好"
    assert result.state.step_count == 1
    assert result.state.tool_call_count == 0
    assert len(provider.requests) == 1
    assert events[-1][0] == "agent.run.completed"


async def test_list_accounts_then_final_answer() -> None:
    runtime, provider = build_runtime(
        [
            LLMResponse(
                tool_calls=[LLMToolCall(id="call_1", name="list_accounts", arguments={})]
            ),
            LLMResponse(content="你有 4 个账户。"),
        ]
    )

    result, events = await run_runtime(runtime)

    assert result.answer == "你有 4 个账户。"
    assert result.state.tool_call_count == 1
    assert '"account_id": "acc_salary"' in provider.requests[1].messages[-1].content
    completed = [data for name, data in events if name == "tool.call.completed"]
    assert completed[0]["item_count"] == 4


async def test_list_accounts_get_balance_then_final_answer() -> None:
    runtime, _ = build_runtime(
        [
            LLMResponse(
                tool_calls=[LLMToolCall(id="call_1", name="list_accounts", arguments={})]
            ),
            LLMResponse(
                tool_calls=[
                    LLMToolCall(
                        id="call_2",
                        name="get_balance",
                        arguments={"account_id": "acc_salary"},
                    )
                ]
            ),
            LLMResponse(content="工资卡余额为 23,864.52 元。"),
        ]
    )

    result, _ = await run_runtime(runtime, "我的工资卡余额是多少？")

    assert result.state.step_count == 3
    assert result.state.tool_call_count == 2
    assert result.answer == "工资卡余额为 23,864.52 元。"


@pytest.mark.parametrize(
    ("call", "caller", "expected_code"),
    [
        (LLMToolCall(id="unknown", name="execute_transfer", arguments={}), None, "TOOL_NOT_FOUND"),
        (
            LLMToolCall(id="denied", name="list_accounts", arguments={}),
            "agent:unknown",
            "TOOL_NOT_ALLOWED",
        ),
        (
            LLMToolCall(id="invalid", name="get_balance", arguments={"wrong": "value"}),
            None,
            "TOOL_ARGUMENT_VALIDATION_FAILED",
        ),
        (
            LLMToolCall(
                id="failure", name="get_balance", arguments={"account_id": "missing"}
            ),
            None,
            "TOOL_EXECUTION_FAILED",
        ),
    ],
)
async def test_tool_error_disposition_is_enforced(
    call: LLMToolCall, caller: str | None, expected_code: str
) -> None:
    runtime, provider = build_runtime(
        [LLMResponse(tool_calls=[call]), LLMResponse(content="无法执行该请求。")]
    )

    if expected_code == "TOOL_ARGUMENT_VALIDATION_FAILED":
        result, _ = await run_runtime(runtime, caller=caller)
        assert result.answer == "无法执行该请求。"
        assert expected_code in provider.requests[1].messages[-1].content
    else:
        with pytest.raises(AgentRuntimeError) as caught:
            await run_runtime(runtime, caller=caller)
        assert caught.value.code == expected_code


async def test_provider_failure_has_external_retryable_semantics() -> None:
    runtime, _ = build_runtime([LLMProviderError("network")])

    with pytest.raises(AgentRuntimeError) as caught:
        await run_runtime(runtime)

    assert caught.value.as_dict() == {
        "category": "EXTERNAL",
        "code": "LLM_PROVIDER_ERROR",
        "message": "LLM provider request failed",
        "retryable": True,
    }


async def test_max_step_limit_stops_never_ending_loop() -> None:
    repeated = LLMResponse(
        tool_calls=[LLMToolCall(id="call", name="list_accounts", arguments={})]
    )
    runtime, _ = build_runtime([repeated, repeated], max_steps=2, max_tool_calls=10)

    with pytest.raises(AgentRuntimeError, match="step limit") as caught:
        await run_runtime(runtime)

    assert caught.value.code == "AGENT_STEP_LIMIT_EXCEEDED"


async def test_max_tool_call_limit_stops_multiple_calls() -> None:
    runtime, _ = build_runtime(
        [
            LLMResponse(
                tool_calls=[
                    LLMToolCall(id="call_1", name="list_accounts", arguments={}),
                    LLMToolCall(id="call_2", name="list_accounts", arguments={}),
                ]
            )
        ],
        max_tool_calls=1,
    )

    with pytest.raises(AgentRuntimeError, match="tool-call limit") as caught:
        await run_runtime(runtime)

    assert caught.value.code == "AGENT_TOOL_CALL_LIMIT_EXCEEDED"


def test_context_contains_only_recent_conversation_and_allowed_tool_schemas() -> None:
    runtime, _ = build_runtime([])
    conversation_id = uuid4()
    messages = [
        Message(
            message_id=uuid4(),
            conversation_id=conversation_id,
            role=(
                MessageRole.USER
                if index % 2 == 0 or index == 11
                else MessageRole.ASSISTANT
            ),
            content=f"message-{index}",
            created_at=datetime.now(UTC),
        )
        for index in range(12)
    ]
    messages.insert(
        6,
        Message(
            message_id=uuid4(),
            conversation_id=conversation_id,
            role=MessageRole.SYSTEM_NOTICE,
            content="internal notice",
            created_at=datetime.now(UTC),
        ),
    )

    request = runtime.context_builder.build(
        agent=MINIMAL_BANKING_AGENT,
        current_task="message-11",
        conversation_messages=messages,
        runtime_messages=[],
        allowed_tools=runtime.registry.resolve(MINIMAL_BANKING_AGENT.allowed_capabilities),
    )

    assert len(request.messages) == 11
    assert "internal notice" not in [message.content for message in request.messages]
    assert [tool.name for tool in request.tools] == ["list_accounts", "get_balance"]
    assert all("balance" not in tool.input_schema.get("properties", {}) for tool in request.tools)
