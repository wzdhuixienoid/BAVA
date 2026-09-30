import json
from uuid import UUID

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from banking_api.agents.financial_analysis_agent import FINANCIAL_ANALYSIS_AGENT
from banking_api.agents.minimal_banking_agent import MINIMAL_BANKING_AGENT
from banking_api.application.conversation_service import ConversationService
from banking_api.application.report_service import ReportPersistenceError
from banking_api.application.task_service import TaskService
from banking_api.context.builder import ContextBuilder
from banking_api.domain.enums import (
    ExecutorType,
    RequestedOutput,
    RuntimeBackend,
    TaskStatus,
)
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.llm.models import LLMResponse, LLMToolCall
from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import EventModel, MessageModel, ReportModel
from banking_api.policy.service import PolicyService
from banking_api.registries.agent_registry import AgentRegistry
from banking_api.registries.skill_registry import SkillRegistry
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.routing.request_router import RequestRouter
from banking_api.runtime.langgraph.graph import LangGraphAgentRuntime
from banking_api.runtime.runtime_factory import AgentRuntimeFactory
from banking_api.runtime.task_runner import UNSUPPORTED_MESSAGE, InProcessTaskRunner
from banking_api.skill_runtime.executor import SkillExecutor
from banking_api.skills.monthly_spending_report import MonthlySpendingReportSkill
from banking_api.tools.banking import (
    build_compare_spending_periods_tool,
    build_get_balance_tool,
    build_get_category_breakdown_tool,
    build_get_spending_summary_tool,
    build_get_top_transactions_tool,
    build_list_accounts_tool,
)
from banking_api.tools.executor import ToolExecutor


def route_response(route: str, requested_output: str = "ANSWER") -> LLMResponse:
    return LLMResponse(
        content=json.dumps(
            {
                "route": route,
                "requested_output": requested_output,
                "confidence": 0.99,
            }
        )
    )


def call(call_id: str, name: str, arguments: dict[str, object]) -> LLMResponse:
    return LLMResponse(
        tool_calls=[LLMToolCall(id=call_id, name=name, arguments=arguments)]
    )


def build_routed_runner(app, responses):  # type: ignore[no-untyped-def]
    provider = FakeLLMProvider(responses)
    bank = MockBankService()
    analytics = FinancialAnalyticsService(bank)
    tools = ToolRegistry()
    tools.register(build_list_accounts_tool(bank))
    tools.register(build_get_balance_tool(bank))
    tools.register(build_get_spending_summary_tool(analytics))
    tools.register(build_get_category_breakdown_tool(analytics))
    tools.register(build_compare_spending_periods_tool(analytics))
    tools.register(build_get_top_transactions_tool(analytics))
    agents = AgentRegistry()
    agents.register(MINIMAL_BANKING_AGENT)
    agents.register(FINANCIAL_ANALYSIS_AGENT)
    skills = SkillRegistry()
    skills.register(MonthlySpendingReportSkill.definition)
    runtime_factory = AgentRuntimeFactory()
    runtime_factory.register(
        RuntimeBackend.LANGGRAPH,
        LangGraphAgentRuntime(
            provider=provider,
            registry=tools,
            executor=ToolExecutor(tools, PolicyService()),
            context_builder=ContextBuilder(),
            checkpointer=InMemorySaver(),
        ),
    )
    return (
        InProcessTaskRunner(
            app.state.test_session_factory,
            app.state.event_bus,
            runtime_factory,
            default_backend=RuntimeBackend.LANGGRAPH,
            router=RequestRouter(provider),
            agent_registry=agents,
            skill_registry=skills,
            skill_executor=SkillExecutor(provider),
        ),
        provider,
    )


def report_narrative() -> LLMResponse:
    return LLMResponse(
        content=json.dumps(
            {
                "headline": "本月支出上升且结构集中",
                "insights": [
                    {
                        "type": "STRUCTURE",
                        "title": "住房是最主要的支出类别",
                        "narrative": "消费结构主要由住房、购物和旅行构成。",
                        "evidence_refs": ["category_breakdown.HOUSING.share"],
                    },
                    {
                        "type": "CHANGE",
                        "title": "旅行和购物是主要增量来源",
                        "narrative": "本月支出明显上升，旅行和购物的变化最突出。",
                        "evidence_refs": [
                            "category_breakdown.TRAVEL.absolute_change",
                            "category_breakdown.SHOPPING.absolute_change",
                        ],
                    },
                ],
            },
            ensure_ascii=False,
        )
    )


async def accept(app, content: str):  # type: ignore[no-untyped-def]
    factory = app.state.test_session_factory
    bus = app.state.event_bus
    async with factory() as session:
        conversation = await ConversationService(session, bus).create(
            user_id="dev-user-001", title="Routing integration"
        )
    async with factory() as session:
        accepted = await ConversationService(
            session,
            bus,
            runtime_backend=RuntimeBackend.LANGGRAPH,
        ).accept_message(
            conversation_id=conversation.conversation_id,
            user_id="dev-user-001",
            content=content,
        )
    return conversation, accepted


async def load_task_and_events(app, task_id: UUID):  # type: ignore[no-untyped-def]
    factory = app.state.test_session_factory
    async with factory() as session:
        task = await TaskService(session).get(task_id, user_id="dev-user-001")
        events = list(
            (
                await session.execute(
                    select(EventModel)
                    .where(EventModel.task_id == task_id)
                    .order_by(EventModel.sequence)
                )
            ).scalars()
        )
    return task, events


async def test_financial_route_persists_executor_snapshot_and_routing_event(app) -> None:
    conversation, accepted = await accept(app, "帮我分析一下2026年8月份消费")
    runner, provider = build_routed_runner(
        app,
        [
            route_response("FINANCIAL_ANALYSIS"),
            call("summary", "get_spending_summary", {"month": "2026-08"}),
            call("compare", "compare_spending_periods", {"month": "2026-08"}),
            call("top", "get_top_transactions", {"month": "2026-08", "limit": 5}),
            LLMResponse(content="8月消费为 16,547.30 元，较 7 月增加 7,214.10 元。"),
        ],
    )

    await runner.run(accepted.task_id)
    task, events = await load_task_and_events(app, accepted.task_id)

    assert task.status is TaskStatus.COMPLETED
    assert task.task_type == "BANKING_REQUEST"
    assert task.executor_type is ExecutorType.AGENT
    assert task.executor_id == "agent:financial-analysis"
    assert task.requested_output is RequestedOutput.ANSWER
    assert task.output is not None
    assert task.output["agent_id"] == "agent:financial-analysis"
    assert UUID(task.output["assistant_message_id"])
    snapshot = task.output["analysis_snapshot"]
    assert snapshot["period"] == "2026-08"
    assert snapshot["account_ids"] == []
    assert snapshot["spending_summary"]["total_spending"] == "16547.30"
    assert snapshot["period_comparison"]["previous_spending"] == "9333.20"
    assert len(snapshot["top_transactions"]["transactions"]) == 5
    routed = next(event for event in events if event.event_type == "request.routed")
    assert routed.data_json == {
        "route": "FINANCIAL_ANALYSIS",
        "requested_output": "ANSWER",
        "executor_id": "agent:financial-analysis",
    }
    assert set(routed.data_json) == {"route", "requested_output", "executor_id"}
    assert provider.requests[1].messages[0].content == FINANCIAL_ANALYSIS_AGENT.instructions
    async with app.state.test_session_factory() as session:
        detail = await ConversationService(session, app.state.event_bus).get(
            conversation_id=conversation.conversation_id,
            user_id="dev-user-001",
        )
    assert detail.messages[-1].content.startswith("8月消费为")


async def test_minimal_route_selects_minimal_agent_and_no_snapshot(app) -> None:
    _, accepted = await accept(app, "我有哪些账户？")
    runner, provider = build_routed_runner(
        app,
        [
            route_response("MINIMAL_BANKING"),
            call("accounts", "list_accounts", {}),
            LLMResponse(content="你有 4 个账户。"),
        ],
    )

    await runner.run(accepted.task_id)
    task, _ = await load_task_and_events(app, accepted.task_id)

    assert task.executor_id == "agent:minimal-banking"
    assert task.output is not None
    assert task.output["agent_id"] == "agent:minimal-banking"
    assert "analysis_snapshot" not in task.output
    assert {tool.name for tool in provider.requests[1].tools} == {
        "list_accounts",
        "get_balance",
    }


async def test_unsupported_route_completes_without_starting_agent(app) -> None:
    conversation, accepted = await accept(app, "帮我买一个理财产品")
    runner, provider = build_routed_runner(app, [route_response("UNSUPPORTED")])

    await runner.run(accepted.task_id)
    task, events = await load_task_and_events(app, accepted.task_id)

    assert task.status is TaskStatus.COMPLETED
    assert task.executor_type is None
    assert task.executor_id is None
    assert task.output is not None
    assert task.output["route"] == "UNSUPPORTED"
    assert len(provider.requests) == 1
    assert "agent.run.started" not in [event.event_type for event in events]
    async with app.state.test_session_factory() as session:
        detail = await ConversationService(session, app.state.event_bus).get(
            conversation_id=conversation.conversation_id,
            user_id="dev-user-001",
        )
    assert detail.messages[-1].content == UNSUPPORTED_MESSAGE


async def test_routing_failure_marks_task_failed_without_selecting_agent(app) -> None:
    _, accepted = await accept(app, "模糊请求")
    runner, provider = build_routed_runner(
        app,
        [LLMResponse(content="bad"), LLMResponse(content='{"route":"ROOT"}')],
    )

    await runner.run(accepted.task_id)
    task, events = await load_task_and_events(app, accepted.task_id)

    assert task.status is TaskStatus.FAILED
    assert task.executor_id is None
    assert task.error == {
        "category": "INTERNAL",
        "code": "ROUTING_FAILED",
        "message": "Request routing failed",
        "retryable": False,
    }
    assert len(provider.requests) == 2
    assert "request.routed" not in [event.event_type for event in events]


async def test_account_specific_snapshot_records_resolved_account_id(app) -> None:
    _, accepted = await accept(app, "分析一下工资卡2026年8月的消费")
    runner, _ = build_routed_runner(
        app,
        [
            route_response("FINANCIAL_ANALYSIS"),
            call("accounts", "list_accounts", {}),
            call(
                "summary",
                "get_spending_summary",
                {"month": "2026-08", "account_ids": ["acc_salary"]},
            ),
            LLMResponse(content="已按工资卡分析8月消费。"),
        ],
    )

    await runner.run(accepted.task_id)
    task, _ = await load_task_and_events(app, accepted.task_id)

    assert task.output is not None
    snapshot = task.output["analysis_snapshot"]
    assert snapshot["account_ids"] == ["acc_salary"]
    assert [item["capability_id"] for item in snapshot["tool_evidence"]] == [
        "account.list",
        "transaction.spending_summary",
    ]
    assert snapshot["tool_evidence"][1]["input"] == {
        "month": "2026-08",
        "account_ids": ["acc_salary"],
    }


async def test_financial_route_cannot_gain_transfer_authority(app) -> None:
    _, accepted = await accept(app, "分析8月消费，然后顺便给张三转1000")
    runner, provider = build_routed_runner(
        app,
        [
            route_response("FINANCIAL_ANALYSIS"),
            call("summary", "get_spending_summary", {"month": "2026-08"}),
            call("write", "execute_transfer", {"payee": "张三", "amount": 1000}),
        ],
    )

    await runner.run(accepted.task_id)
    task, events = await load_task_and_events(app, accepted.task_id)

    assert task.status is TaskStatus.FAILED
    assert task.executor_id == "planner:constrained"
    assert task.error["code"] == "PLAN_PLANNER_NOT_CONFIGURED"
    assert len(provider.requests) == 1
    assert not any(event.event_type.startswith("agent.") for event in events)
    assert not any(event.event_type.startswith("tool.") for event in events)


async def test_monthly_report_product_pipeline_persists_one_visible_message(app) -> None:
    conversation, accepted = await accept(app, "生成一份2026年8月份消费报告")
    runner, provider = build_routed_runner(
        app,
        [
            route_response("FINANCIAL_ANALYSIS", "MONTHLY_REPORT"),
            call("summary", "get_spending_summary", {"month": "2026-08"}),
            call("categories", "get_category_breakdown", {"month": "2026-08"}),
            call("compare", "compare_spending_periods", {"month": "2026-08"}),
            call("top", "get_top_transactions", {"month": "2026-08", "limit": 5}),
            LLMResponse(content="数据收集完成。"),
            report_narrative(),
        ],
    )

    await runner.run(accepted.task_id)
    # A terminal Task is not claimable again; retry cannot duplicate the
    # immutable Report or the final assistant message.
    await runner.run(accepted.task_id)
    task, events = await load_task_and_events(app, accepted.task_id)

    assert task.status is TaskStatus.COMPLETED
    assert task.requested_output is RequestedOutput.MONTHLY_REPORT
    assert task.executor_id == "agent:financial-analysis"
    assert task.output is not None
    assert task.output["requested_output"] == "MONTHLY_REPORT"
    assert task.output["skill_id"] == "skill:monthly-spending-report"
    assert task.output["skill_version"] == 1
    assert task.output["report_type"] == "MONTHLY_SPENDING"
    assert UUID(task.output["report_id"])
    assert task.output["analysis_snapshot"]["spending_summary"][
        "total_spending"
    ] == "16547.30"

    event_types = [event.event_type for event in events]
    assert event_types.index("skill.run.started") < event_types.index(
        "skill.run.completed"
    )
    assert event_types.index("skill.run.completed") < event_types.index(
        "report.generated"
    )
    assert event_types.index("report.generated") < event_types.index("task.completed")
    generated = next(event for event in events if event.event_type == "report.generated")
    assert generated.data_json == {
        "report_id": task.output["report_id"],
        "report_type": "MONTHLY_SPENDING",
        "period": "2026-08",
        "source_task_id": str(accepted.task_id),
    }
    assert "content" not in generated.data_json
    for event_type in ("skill.run.started", "skill.run.completed"):
        skill_event = next(event for event in events if event.event_type == event_type)
        assert skill_event.data_json == {
            "skill_id": "skill:monthly-spending-report",
            "skill_version": 1,
            "task_id": str(accepted.task_id),
        }

    async with app.state.test_session_factory() as session:
        report = (
            await session.execute(
                select(ReportModel).where(ReportModel.source_task_id == accepted.task_id)
            )
        ).scalar_one()
        assistant_messages = list(
            (
                await session.execute(
                    select(MessageModel).where(
                        MessageModel.conversation_id == conversation.conversation_id,
                        MessageModel.role == "ASSISTANT",
                    )
                )
            ).scalars()
        )
    assert str(report.report_id) == task.output["report_id"]
    assert report.content_json["overview"]["total_spending"] == "16547.30"
    assert [message.content for message in assistant_messages] == [
        "2026年8月消费报告已生成。"
    ]
    assert "数据收集完成" not in assistant_messages[0].content
    assert len(provider.requests) == 7


async def test_normal_financial_answer_does_not_create_report(app) -> None:
    _, accepted = await accept(app, "分析2026年8月消费")
    runner, provider = build_routed_runner(
        app,
        [
            route_response("FINANCIAL_ANALYSIS"),
            call("summary", "get_spending_summary", {"month": "2026-08"}),
            LLMResponse(content="本月消费分析完成。"),
        ],
    )

    await runner.run(accepted.task_id)

    async with app.state.test_session_factory() as session:
        reports = list((await session.execute(select(ReportModel))).scalars())
    assert reports == []


async def test_incomplete_report_snapshot_fails_without_artifact(app) -> None:
    _, accepted = await accept(app, "生成2026年8月消费报告")
    runner, _ = build_routed_runner(
        app,
        [
            route_response("FINANCIAL_ANALYSIS", "MONTHLY_REPORT"),
            call("summary", "get_spending_summary", {"month": "2026-08"}),
            LLMResponse(content="数据收集完成。"),
        ],
    )

    await runner.run(accepted.task_id)
    task, events = await load_task_and_events(app, accepted.task_id)

    assert task.status is TaskStatus.FAILED
    assert task.error is not None
    assert task.error["code"] == "REPORT_INPUT_INCOMPLETE"
    assert "skill.run.started" in [event.event_type for event in events]
    assert "skill.run.failed" in [event.event_type for event in events]
    assert "report.generated" not in [event.event_type for event in events]
    async with app.state.test_session_factory() as session:
        assert list((await session.execute(select(ReportModel))).scalars()) == []


async def test_report_persistence_failure_emits_no_generated_event(
    app, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    _, accepted = await accept(app, "生成2026年8月消费报告")
    runner, _ = build_routed_runner(
        app,
        [
            route_response("FINANCIAL_ANALYSIS", "MONTHLY_REPORT"),
            call("summary", "get_spending_summary", {"month": "2026-08"}),
            call("categories", "get_category_breakdown", {"month": "2026-08"}),
            call("compare", "compare_spending_periods", {"month": "2026-08"}),
            call("top", "get_top_transactions", {"month": "2026-08", "limit": 5}),
            LLMResponse(content="数据收集完成。"),
            report_narrative(),
        ],
    )

    async def fail_persistence(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise ReportPersistenceError("database unavailable")

    monkeypatch.setattr(
        "banking_api.runtime.task_runner.ReportService.create_report",
        fail_persistence,
    )
    await runner.run(accepted.task_id)
    task, events = await load_task_and_events(app, accepted.task_id)

    assert task.status is TaskStatus.FAILED
    assert task.error is not None
    assert task.error["code"] == "REPORT_PERSISTENCE_FAILED"
    assert "skill.run.completed" in [event.event_type for event in events]
    assert "report.generated" not in [event.event_type for event in events]
    assert "task.completed" not in [event.event_type for event in events]


async def test_report_request_cannot_gain_transfer_authority(app) -> None:
    _, accepted = await accept(app, "生成8月消费报告，然后给张三转1000")
    runner, provider = build_routed_runner(
        app,
        [
            route_response("FINANCIAL_ANALYSIS", "MONTHLY_REPORT"),
            call("summary", "get_spending_summary", {"month": "2026-08"}),
            call("write", "execute_transfer", {"payee": "张三", "amount": 1000}),
        ],
    )

    await runner.run(accepted.task_id)
    task, events = await load_task_and_events(app, accepted.task_id)

    assert task.status is TaskStatus.COMPLETED
    assert task.executor_id is None
    assert task.output is not None
    assert task.output["route"] == "UNSUPPORTED"
    assert len(provider.requests) == 1
    assert "skill.run.started" not in [event.event_type for event in events]
    assert "report.generated" not in [event.event_type for event in events]
