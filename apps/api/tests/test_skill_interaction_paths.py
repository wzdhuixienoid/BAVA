"""Public conversation API through the production router, runner, tools and skill bindings."""

from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import func, select
from test_routing_integration import call, report_narrative, route_response
from test_wealth import USER
from test_wealth import wealth as wealth
from test_wealth_repairs import reassemble

from banking_api.agent_skills import packaged_catalog
from banking_api.context.builder import ContextBuilder
from banking_api.domain.enums import RuntimeBackend
from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.llm.models import LLMResponse
from banking_api.persistence.models import EventModel, OperationModel, TaskModel
from banking_api.routing.request_router import RequestRouter
from banking_api.runtime.langgraph.graph import LangGraphAgentRuntime
from banking_api.skill_runtime.executor import SkillExecutor


def assemble(wealth, monkeypatch, route, responses, requested_output="ANSWER"):
    app, _ = reassemble(wealth, monkeypatch, True)
    provider = FakeLLMProvider(responses)
    app.state.runtime_factory.register(
        RuntimeBackend.LANGGRAPH,
        LangGraphAgentRuntime(
            provider=provider,
            registry=app.state.tool_registry,
            executor=app.state.transfer_workflow_engine._executor,
            context_builder=ContextBuilder(),
            checkpointer=InMemorySaver(),
        ),
    )
    runner = app.state.task_runner
    runner.default_backend = RuntimeBackend.LANGGRAPH
    runner.router = RequestRouter(FakeLLMProvider([route_response(route, requested_output)]))
    runner.skill_executor = SkillExecutor(provider)
    return app, runner


async def interact(app, runner, factory, content):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/v1/conversations", json={"title": "Skill 路径核验"})
        assert created.status_code == 201
        cid = created.json()["conversation_id"]
        accepted = await client.post(
            f"/api/v1/conversations/{cid}/messages", json={"content": content}
        )
        assert accepted.status_code == 202
        tid = UUID(accepted.json()["task_id"])
        await runner.run(tid)
        detail = await client.get(f"/api/v1/conversations/{cid}")
        assert detail.status_code == 200
        messages = detail.json()["messages"]
    async with factory() as session:
        task = await session.get(TaskModel, tid)
        assert task.user_id == USER
        assert task.status in {"COMPLETED", "WAITING_USER"}, task.error_json
        events = list(await session.scalars(select(EventModel).where(EventModel.task_id == tid)))
        assert await session.scalar(select(func.count()).select_from(OperationModel)) == 0
    if task.status == "WAITING_USER":
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            workflow = await client.get(f"/api/v1/workflows/{task.output_json['workflow_id']}")
            assert workflow.status_code == 200
            assert workflow.json()["status"] == "WAITING_FOR_INPUT"
    else:
        assert any(m["role"] == "ASSISTANT" for m in messages)
    return task, events


@pytest.mark.parametrize(
    "text,route,skill,responses",
    [
        (
            "查看我的账户",
            "ACCOUNT_QUERY",
            "banking-assistance",
            [call("accounts", "list_accounts", {}), LLMResponse(content="账户查询完成。")],
        ),
        (
            "分析2026年8月消费",
            "FINANCIAL_ANALYSIS",
            "financial-analysis",
            [
                call("summary", "get_spending_summary", {"month": "2026-08"}),
                LLMResponse(content="消费查询完成。"),
            ],
        ),
        (
            "分析我的订阅",
            "SUBSCRIPTION_ANALYSIS",
            "subscription-analysis",
            [
                call("subscriptions", "analyze_subscriptions", {}),
                LLMResponse(content="订阅查询完成。"),
            ],
        ),
        # Exercise the real page's messages and the supported deterministic fallback.
        (
            "请根据我的需求提供个性化模拟理财推荐。请先进行只读分析。",
            "WEALTH_ANALYSIS",
            "wealth-advisory",
            [LLMResponse(content="invalid")],
        ),
        (
            "请对比以下模拟理财产品：演示均衡优选、演示均衡周享，说明风险、费用与到账安排。"
            "请先进行只读分析。",
            "WEALTH_ANALYSIS",
            "wealth-advisory",
            [LLMResponse(content="invalid")],
        ),
        ("赎回演示均衡优选", "WEALTH_ANALYSIS", "wealth-trade-assistance", []),
    ],
)
async def test_public_message_reaches_standard_skill_and_visible_reply(
    wealth, monkeypatch, text, route, skill, responses
):
    app, runner = assemble(wealth, monkeypatch, route, responses)
    task, events = await interact(app, runner, wealth[0], text)
    if skill.startswith("wealth-"):
        activation = next(e.data_json for e in events if e.event_type == "agent_skill.activated")
        assert activation["skill_id"] == skill
        assert activation["skill_version"] == packaged_catalog().entries[skill]["version"]
        assert activation["resource_hashes"]
        analysis = task.output_json.get("wealth_analysis")
        if analysis:
            assert analysis["answer"]["skill_resource_hashes"] == activation["resource_hashes"]
    else:
        started = next(e.data_json for e in events if e.event_type == "agent.run.started")
        assert started["skills"][0]["skill_id"] == skill
        assert started["skills"][0]["resource_hashes"]


async def test_public_report_request_runs_both_standard_packages(wealth, monkeypatch):
    app, runner = assemble(
        wealth,
        monkeypatch,
        "FINANCIAL_ANALYSIS",
        [
            call("summary", "get_spending_summary", {"month": "2026-08"}),
            call("categories", "get_category_breakdown", {"month": "2026-08"}),
            call("compare", "compare_spending_periods", {"month": "2026-08"}),
            call("top", "get_top_transactions", {"month": "2026-08", "limit": 5}),
            LLMResponse(content="数据收集完成。"),
            report_narrative(),
        ],
        requested_output="MONTHLY_REPORT",
    )
    task, events = await interact(app, runner, wealth[0], "生成2026年8月消费报告")
    assert task.output_json["report_id"]
    assert task.output_json["skill_package"]["skill_id"] == "monthly-spending-report"
    started = next(e.data_json for e in events if e.event_type == "agent.run.started")
    assert "references/report-source.md" in started["skills"][0]["resource_hashes"]


async def test_blocked_trade_keeps_skill_audit_after_transaction_rollback(wealth, monkeypatch):
    app, runner = assemble(wealth, monkeypatch, "WEALTH_ANALYSIS", [])
    _, events = await interact(app, runner, wealth[0], "用工资卡购买演示均衡优选5000元")
    for event_type in ("agent_skill.activated", "agent_skill.failed"):
        event = next(e.data_json for e in events if e.event_type == event_type)
        assert event["skill_id"] == "wealth-trade-assistance"
        assert event["resource_hashes"]
        assert event["error_code"] == "ASSESSMENT_REQUIRED"
