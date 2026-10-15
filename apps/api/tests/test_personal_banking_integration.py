"""One executor identity, least-privilege skill profiles, durable routing and combined answers."""

from uuid import UUID

import pytest
from sqlalchemy import func, select
from test_routing_integration import build_routed_runner, call, report_narrative, route_response

from banking_api.agents.personal_banking_agent import (
    ACCOUNT_CAPABILITIES,
    PERSONAL_BANKING_AGENT_ID,
    SPENDING_CAPABILITIES,
    PersonalBankingMode,
    personal_banking_agent,
)
from banking_api.domain.enums import ExecutorType, RequestedOutput, RuntimeBackend
from banking_api.financial.anomaly_detector import TransactionAnomalyDetector
from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.llm.models import LLMResponse, LLMToolCall
from banking_api.main import create_app
from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import EventModel, OperationModel, PlanModel, TaskModel
from banking_api.planning.models import PlanCapability
from banking_api.planning.registry import PlanCapabilityRegistry
from banking_api.routing.models import RequestRoute
from banking_api.routing.request_router import RequestRouter, RoutingError
from banking_api.runtime.task_runner import InProcessTaskRunner
from banking_api.tools.banking import build_detect_anomalies_tool


async def interact(app, client, responses, prompt, *, legacy_executor=None, anomalies=False):
    runner, provider = build_routed_runner(app, responses)
    if anomalies:
        runner.runtime_factory.get(RuntimeBackend.LANGGRAPH).registry.register(
            build_detect_anomalies_tool(TransactionAnomalyDetector(MockBankService()))
        )
    app.state.task_runner = runner
    conversation = await client.post("/api/v1/conversations", json={"title": "个人银行整合验收"})
    assert conversation.status_code == 201
    cid = conversation.json()["conversation_id"]
    accepted = await client.post(f"/api/v1/conversations/{cid}/messages", json={"content": prompt})
    assert accepted.status_code == 202
    tid = UUID(accepted.json()["task_id"])
    if legacy_executor:
        async with app.state.test_session_factory() as session:
            task = await session.get(TaskModel, tid)
            task.executor_type = ExecutorType.AGENT
            task.executor_id = legacy_executor
            task.requested_output = RequestedOutput.ANSWER
            await session.commit()
    await runner.run(tid)
    async with app.state.test_session_factory() as session:
        task = await session.get(TaskModel, tid)
        events = list(await session.scalars(select(EventModel).where(EventModel.task_id == tid)))
        assert task.status == "COMPLETED", task.error_json
        assert await session.scalar(select(func.count()).select_from(OperationModel)) == 0
        assert await session.scalar(select(func.count()).select_from(PlanModel)) == 0
    detail = (await client.get(f"/api/v1/conversations/{cid}")).json()
    return task, events, provider, detail["messages"][-1]["content"]


def test_one_registered_identity_and_three_scoped_skill_profiles():
    app = create_app()
    assert {a.agent_id for a in app.state.agent_registry.all()} == {
        PERSONAL_BANKING_AGENT_ID,
        "agent:subscription-analysis",
        "agent:wealth-advisor",
    }
    expected = {
        PersonalBankingMode.ACCOUNT: (ACCOUNT_CAPABILITIES, {"banking-assistance"}),
        PersonalBankingMode.SPENDING: (SPENDING_CAPABILITIES, {"financial-analysis"}),
        PersonalBankingMode.COMBINED: (
            ACCOUNT_CAPABILITIES | SPENDING_CAPABILITIES,
            {"banking-assistance", "financial-analysis"},
        ),
    }
    for mode, (capabilities, skills) in expected.items():
        agent = personal_banking_agent(mode)
        agent.validate_skills()
        assert agent.agent_id == PERSONAL_BANKING_AGENT_ID
        assert agent.allowed_capabilities == capabilities
        assert {s.skill_id for s in agent.skills} == skills
        assert all(not app.state.tool_registry.get(c).side_effect for c in capabilities)
    account = personal_banking_agent(PersonalBankingMode.ACCOUNT)
    assert "analysis-rules.md" not in account.skills[0].resources
    registry = PlanCapabilityRegistry()
    assert (
        registry.get(PlanCapability.ACCOUNT_QUERY).executor_id
        == registry.get(PlanCapability.FINANCIAL_ANALYSIS).executor_id
        == PERSONAL_BANKING_AGENT_ID
    )


@pytest.mark.parametrize("report", [False, True])
async def test_combination_routes_to_one_agent_instead_of_plan(report):
    provider = FakeLLMProvider(
        [
            route_response(
                "FINANCIAL_ANALYSIS" if report else "COMPLEX_PLAN",
                "MONTHLY_REPORT" if report else "ANSWER",
            )
        ]
    )
    decision = await RequestRouter(provider).route(
        "查工资卡余额，" + ("生成2026年8月消费报告" if report else "分析2026年8月消费")
    )
    assert decision.route == RequestRoute.PERSONAL_BANKING


@pytest.mark.parametrize(
    "prompt,route",
    [
        ("查工资卡余额", RequestRoute.ACCOUNT_QUERY),
        ("分析2026年8月消费", RequestRoute.FINANCIAL_ANALYSIS),
    ],
)
async def test_model_cannot_enable_combined_profile_for_a_single_purpose(prompt, route):
    provider = FakeLLMProvider([route_response("PERSONAL_BANKING")])
    assert (await RequestRouter(provider).route(prompt)).route == route


async def test_all_account_balances_can_use_five_calls_without_loading_spending_skill(app, client):
    calls = [
        LLMToolCall(id=name, name="get_balance", arguments={"account_id": name})
        for name in ("acc_salary", "acc_savings", "acc_credit", "acc_travel")
    ]
    task, events, provider, _ = await interact(
        app,
        client,
        [
            route_response("ACCOUNT_QUERY"),
            call("list", "list_accounts", {}),
            LLMResponse(tool_calls=calls),
            LLMResponse(content="已查询各账户余额。"),
        ],
        "查询我的所有账户余额",
    )
    assert task.output_json["tool_calls"] == 5
    assert len(task.output_json["account_results"]) == 5
    assert "analysis_snapshot" not in task.output_json
    assert {t.name for t in provider.requests[1].tools} == {
        "list_accounts",
        "get_balance",
        "get_account_statement",
    }
    started = next(e for e in events if e.event_type == "agent.run.started")
    assert [s["skill_id"] for s in started.data_json["skills"]] == ["banking-assistance"]


async def test_combined_request_persists_both_facts_without_a_plan(app, client):
    task, events, provider, _ = await interact(
        app,
        client,
        [
            route_response("COMPLEX_PLAN"),
            call("list", "list_accounts", {}),
            call("balance", "get_balance", {"account_id": "acc_salary"}),
            call("summary", "get_spending_summary", {"month": "2026-08"}),
            call("categories", "get_category_breakdown", {"month": "2026-08"}),
            LLMResponse(content="已查询当前余额并分析八月消费。"),
        ],
        "查工资卡余额，再分析2026年8月消费",
    )
    assert task.executor_id == PERSONAL_BANKING_AGENT_ID
    assert task.input_json["personal_banking_route"] == "PERSONAL_BANKING"
    assert task.output_json["account_results"][-1]["balance"] == "23864.52"
    assert task.output_json["analysis_snapshot"]["spending_summary"]["total_spending"] == "16547.30"
    assert {
        s["skill_id"]
        for e in events
        if e.event_type == "agent.run.started"
        for s in e.data_json["skills"]
    } == {"banking-assistance", "financial-analysis"}
    exposed = {t.name for t in provider.requests[1].tools}
    assert "get_balance" in exposed and "get_spending_summary" in exposed
    assert "detect_transaction_anomalies" not in exposed


async def test_balance_plus_report_keeps_account_facts_outside_report_metrics(app, client):
    task, _, _, answer = await interact(
        app,
        client,
        [
            route_response("PERSONAL_BANKING", "MONTHLY_REPORT"),
            call("list", "list_accounts", {}),
            call("balance", "get_balance", {"account_id": "acc_salary"}),
            call("summary", "get_spending_summary", {"month": "2026-08"}),
            call("categories", "get_category_breakdown", {"month": "2026-08"}),
            call("compare", "compare_spending_periods", {"month": "2026-08"}),
            LLMResponse(content="报告数据已准备。"),
            report_narrative(),
        ],
        "查工资卡余额，并生成2026年8月消费报告",
    )
    assert task.output_json["report_id"]
    assert task.output_json["account_results"][-1]["balance_display"] == "¥23,864.52"
    assert task.output_json["analysis_snapshot"]["spending_summary"]["total_spending"] == "16547.30"
    assert "工资卡当前余额：¥23,864.52" in answer and "消费报告已生成" in answer


@pytest.mark.parametrize(
    "old_id,tool,args,skill",
    [
        (
            "agent:minimal-banking",
            "get_balance",
            {"account_id": "acc_salary"},
            "banking-assistance",
        ),
        (
            "agent:financial-analysis",
            "get_spending_summary",
            {"month": "2026-08"},
            "financial-analysis",
        ),
    ],
)
async def test_legacy_task_executor_recovers_without_rerouting_or_expanding_scope(
    app, client, old_id, tool, args, skill
):
    task, events, provider, _ = await interact(
        app,
        client,
        [
            call("read", tool, args),
            LLMResponse(content="查询完成。"),
        ],
        "恢复已有查询",
        legacy_executor=old_id,
    )
    assert task.executor_id == old_id  # Historical execution evidence is preserved.
    assert task.output_json["agent_id"] == PERSONAL_BANKING_AGENT_ID
    started = next(e for e in events if e.event_type == "agent.run.started")
    assert [s["skill_id"] for s in started.data_json["skills"]] == [skill]
    assert provider.requests[0].tools  # No model router request occurred.


def test_new_executor_cannot_resume_with_missing_or_invalid_persisted_scope():
    for scope in (None, "TRANSFER_WORKFLOW"):
        with pytest.raises(RoutingError):
            InProcessTaskRunner._durable_route(
                executor_type=ExecutorType.AGENT,
                executor_id=PERSONAL_BANKING_AGENT_ID,
                requested_output=RequestedOutput.ANSWER,
                personal_banking_route=scope,
            )


async def test_combined_anomaly_answer_preserves_backend_balance_facts(app, client):
    task, _, _, answer = await interact(
        app,
        client,
        [
            route_response("PERSONAL_BANKING"),
            call("list", "list_accounts", {}),
            call("balance", "get_balance", {"account_id": "acc_salary"}),
            call("anomalies", "detect_transaction_anomalies", {"analysis_days": 30}),
            LLMResponse(content="这段模型文字应由确定性异常回答替代。"),
        ],
        "查询工资卡余额，并检查近30天异常交易",
        anomalies=True,
    )
    assert "工资卡当前余额：¥23,864.52" in answer
    assert "异常" in answer and "这段模型文字" not in answer
    assert task.output_json["account_results"][-1]["kind"] == "ACCOUNT_BALANCE"
    assert task.output_json["transaction_anomaly_snapshot"]


async def test_spending_account_resolution_does_not_create_an_account_query_result(app, client):
    task, _, _, _ = await interact(
        app,
        client,
        [
            route_response("FINANCIAL_ANALYSIS"),
            call("list", "list_accounts", {}),
            call(
                "summary",
                "get_spending_summary",
                {"month": "2026-08", "account_ids": ["acc_salary"]},
            ),
            LLMResponse(content="工资卡八月消费已分析。"),
        ],
        "分析工资卡2026年8月消费",
    )
    assert "account_results" not in task.output_json
    assert all(
        e["capability_id"].startswith("transaction.")
        for e in task.output_json["analysis_snapshot"]["tool_evidence"]
    )
