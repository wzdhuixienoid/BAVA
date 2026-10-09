from datetime import UTC, datetime
from decimal import Decimal

import pytest
from banking_test_helpers import authenticate_workflow
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError
from test_transfer_authorization import create_ready_workflow
from test_transfer_operations import operation_runtime

from banking_api.agents.minimal_banking_agent import MINIMAL_BANKING_AGENT
from banking_api.application.conversation_service import ConversationService
from banking_api.application.operation_service import OperationService
from banking_api.application.workflow_service import WorkflowService
from banking_api.config.settings import Settings
from banking_api.context.builder import ContextBuilder
from banking_api.domain.account import AccountBalanceResult
from banking_api.domain.enums import OperationStatus, RuntimeBackend
from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.llm.models import LLMResponse, LLMToolCall
from banking_api.persistence.models import TaskModel
from banking_api.policy.service import PolicyService
from banking_api.runtime.langgraph.graph import LangGraphAgentRuntime
from banking_api.runtime.manual_agent_runtime import ManualAgentRuntime
from banking_api.runtime.runtime_factory import AgentRuntimeFactory
from banking_api.runtime.task_runner import InProcessTaskRunner
from banking_api.tools.executor import ToolExecutor


def account_runner(app, registry, responses, backend):
    kwargs = {
        "provider": FakeLLMProvider(responses),
        "registry": registry,
        "executor": ToolExecutor(registry, PolicyService()),
        "context_builder": ContextBuilder(),
    }
    runtime = (
        LangGraphAgentRuntime(**kwargs, checkpointer=InMemorySaver())
        if backend is RuntimeBackend.LANGGRAPH
        else ManualAgentRuntime(**kwargs, agent=MINIMAL_BANKING_AGENT)
    )
    factory = AgentRuntimeFactory()
    factory.register(backend, runtime)
    return InProcessTaskRunner(
        app.state.test_session_factory, app.state.event_bus, factory, default_backend=backend
    )


async def query(app, runner, text="工资卡余额多少？"):
    async with app.state.test_session_factory() as session:
        service = ConversationService(
            session, app.state.event_bus, runtime_backend=runner.default_backend
        )
        conversation = await service.create(user_id="dev-user-001", title="余额事实")
        accepted = await service.accept_message(
            conversation_id=conversation.conversation_id, user_id="dev-user-001", content=text
        )
    await runner.run(accepted.task_id)
    return accepted.task_id


def balance_responses(answer="你的余额是 1 元。"):
    return [
        LLMResponse(tool_calls=[LLMToolCall(id="list", name="list_accounts", arguments={})]),
        LLMResponse(
            tool_calls=[
                LLMToolCall(
                    id="balance", name="get_balance", arguments={"account_id": "acc_salary"}
                )
            ]
        ),
        LLMResponse(content=answer),
    ]


@pytest.mark.parametrize("backend", [RuntimeBackend.MANUAL, RuntimeBackend.LANGGRAPH])
async def test_false_llm_prose_cannot_pollute_persisted_or_api_balance(app, client, backend):
    _, _, registry, _ = operation_runtime(app)
    started = datetime.now(UTC)
    runner = account_runner(app, registry, balance_responses(), backend)
    task_id = await query(app, runner)
    response = await client.get(f"/api/v1/tasks/{task_id}")
    assert response.status_code == 200
    task = response.json()
    assert task["status"] == "COMPLETED"
    results = task["output"]["account_results"]
    assert results[0]["kind"] == "ACCOUNT_LIST"
    balance = results[1]
    assert balance["kind"] == "ACCOUNT_BALANCE"
    assert balance["account_id"] == "acc_salary"
    assert balance["display_name"] == "工资卡"
    assert balance["masked_number"] == "****6688"
    assert balance["account_type"] == "DEBIT"
    assert balance["currency"] == "CNY"
    assert balance["balance"] == "23864.52"
    assert balance["balance_display"] == "¥23,864.52"
    assert started <= datetime.fromisoformat(balance["as_of"]) <= datetime.now(UTC)
    async with app.state.test_session_factory() as session:
        persisted = await session.get(TaskModel, task_id)
        assert persisted.output_json["account_results"] == results
    conversation = (await client.get(f"/api/v1/conversations/{task['conversation_id']}")).json()
    assert conversation["messages"][-1]["content"] == "你的余额是 1 元。"
    tasks = (
        await client.get("/api/v1/tasks", params={"conversation_id": task["conversation_id"]})
    ).json()
    assert tasks[0]["output"]["account_results"] == results


async def test_standalone_account_list_is_typed_and_bounded(app, client):
    _, _, registry, _ = operation_runtime(app)
    runner = account_runner(
        app,
        registry,
        [
            LLMResponse(tool_calls=[LLMToolCall(id="list", name="list_accounts", arguments={})]),
            LLMResponse(content="你有一个不存在的账户。"),
        ],
        RuntimeBackend.LANGGRAPH,
    )
    task_id = await query(app, runner, "我有哪些账户？")
    result = (await client.get(f"/api/v1/tasks/{task_id}")).json()["output"]["account_results"][0]
    assert result["kind"] == "ACCOUNT_LIST"
    assert len(result["accounts"]) == 4
    assert result["accounts"][0]["masked_number"] == "****6688"
    assert "balance" not in result["accounts"][0]
    assert result["as_of"]
    schema = app.openapi()["components"]["schemas"]
    assert schema["AccountListResult"]["properties"]["accounts"]["maxItems"] == 100
    assert schema["AccountBalanceResult"]["properties"]["balance"]["type"] == "string"
    assert "account_results" in schema["TaskOutput"]["properties"]
    assert schema["TaskOutput"]["properties"]["account_results"]["maxItems"] == 100


@pytest.mark.parametrize("backend", [RuntimeBackend.MANUAL, RuntimeBackend.LANGGRAPH])
@pytest.mark.parametrize("batched", [False, True])
async def test_all_account_balances_complete_with_default_budget(app, client, backend, batched):
    _, _, registry, _ = operation_runtime(app)
    account_ids = ["acc_salary", "acc_savings", "acc_credit", "acc_travel"]
    calls = [
        LLMToolCall(id=account_id, name="get_balance", arguments={"account_id": account_id})
        for account_id in account_ids
    ]
    responses = [
        LLMResponse(tool_calls=[LLMToolCall(id="list", name="list_accounts", arguments={})]),
        *(
            [LLMResponse(tool_calls=calls)]
            if batched
            else [LLMResponse(tool_calls=[call]) for call in calls]
        ),
        LLMResponse(content="已查到各账户余额，请查看账户卡片。"),
    ]
    runner = account_runner(app, registry, responses, backend)
    task_id = await query(app, runner, "我账户里有多少钱")
    task = (await client.get(f"/api/v1/tasks/{task_id}")).json()
    assert task["status"] == "COMPLETED"
    assert task["output"]["tool_calls"] == 5
    results = task["output"]["account_results"]
    assert results[0]["kind"] == "ACCOUNT_LIST"
    assert [item["account_id"] for item in results[1:]] == account_ids
    assert [item["balance"] for item in results[1:]] == [
        "23864.52",
        "78620.00",
        "-4860.35",
        "12680.40",
    ]


def test_default_settings_allow_full_account_balance_query(monkeypatch):
    monkeypatch.delenv("AGENT_MAX_TOOL_CALLS", raising=False)
    settings = Settings(_env_file=None, auth_mode="development")
    assert settings.agent_max_tool_calls == 8


async def test_balance_after_successful_transfer_uses_provider_ledger(app, client):
    _, provider, registry, engine = operation_runtime(app)
    before = await query(
        app, account_runner(app, registry, balance_responses(), RuntimeBackend.LANGGRAPH)
    )
    assert (await client.get(f"/api/v1/tasks/{before}")).json()["output"]["account_results"][1][
        "balance"
    ] == "23864.52"
    workflow = await create_ready_workflow(
        app, app.state.event_bus, engine, user_id="dev-user-001", amount=Decimal("500.00")
    )
    async with app.state.test_session_factory() as session:
        ready = await WorkflowService(session, app.state.event_bus, engine).approve(
            workflow.workflow_id, user_id=workflow.user_id, expected_version=workflow.version
        )
    ready = await authenticate_workflow(app, engine, ready)
    async with app.state.test_session_factory() as session:
        operation = await OperationService(session, app.state.event_bus, engine).commit_workflow(
            ready.workflow_id, user_id=ready.user_id, expected_version=ready.version
        )
    assert operation.status is OperationStatus.SUCCEEDED
    assert await provider.transfer_count() == 1
    after = await query(
        app, account_runner(app, registry, balance_responses(), RuntimeBackend.LANGGRAPH)
    )
    balance = (await client.get(f"/api/v1/tasks/{after}")).json()["output"]["account_results"][1]
    assert balance["balance"] == "23364.52"
    assert balance["balance_display"] == "¥23,364.52"


@pytest.mark.parametrize("balance", [23864.52, "NaN", "Infinity"])
def test_balance_fact_rejects_float_and_nonfinite_values(balance):
    with pytest.raises(ValidationError):
        AccountBalanceResult(
            account_id="acc_salary",
            display_name="工资卡",
            masked_number="****6688",
            account_type="DEBIT",
            currency="CNY",
            balance=balance,
            as_of=datetime.now(UTC),
        )
