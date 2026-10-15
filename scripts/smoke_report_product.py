"""Opt-in real DeepSeek smoke for the complete report product pipeline."""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlparse

from banking_api.agents.personal_banking_agent import PERSONAL_BANKING_AGENT
from banking_api.api.dependencies import get_session
from banking_api.application.conversation_service import ConversationService
from banking_api.application.task_service import TaskService
from banking_api.config.settings import Settings
from banking_api.context.builder import ContextBuilder
from banking_api.domain.enums import MessageRole, RuntimeBackend, TaskStatus
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.financial.report_models import MonthlySpendingReportCore
from banking_api.llm.openai_compatible_provider import OpenAICompatibleProvider
from banking_api.main import create_app
from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.database import session_factory
from banking_api.persistence.models import EventModel
from banking_api.policy.service import PolicyService
from banking_api.registries.agent_registry import AgentRegistry
from banking_api.registries.skill_registry import SkillRegistry
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.routing.request_router import RequestRouter
from banking_api.runtime.event_bus import EventBus
from banking_api.runtime.langgraph.checkpoint import LangGraphCheckpointManager
from banking_api.runtime.langgraph.graph import LangGraphAgentRuntime
from banking_api.runtime.runtime_factory import AgentRuntimeFactory
from banking_api.runtime.task_runner import InProcessTaskRunner
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
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

DATA_DIR = (
    Path(__file__).parents[1]
    / "apps"
    / "api"
    / "src"
    / "banking_api"
    / "mock_bank"
    / "data"
)
USER_ID = "dev-user-001"


async def main() -> None:
    settings = Settings()
    if not settings.llm_base_url or not settings.llm_api_key or not settings.llm_model:
        raise SystemExit("LLM_BASE_URL, LLM_API_KEY and LLM_MODEL are required")
    print(
        "provider.config",
        {
            "provider": settings.llm_provider,
            "base_url_domain": urlparse(settings.llm_base_url).netloc,
            "model": settings.llm_model,
        },
    )

    provider = OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
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
    agents.register(PERSONAL_BANKING_AGENT)
    skills = SkillRegistry()
    skills.register(MonthlySpendingReportSkill.definition)
    bus = EventBus()
    checkpoint_manager = LangGraphCheckpointManager(
        settings.langgraph_checkpoint_database_url or settings.database_url,
        strict_msgpack=settings.langgraph_strict_msgpack,
    )
    runtime_factory = AgentRuntimeFactory()
    runtime_factory.register(
        RuntimeBackend.LANGGRAPH,
        LangGraphAgentRuntime(
            provider=provider,
            registry=tools,
            executor=ToolExecutor(tools, PolicyService()),
            context_builder=ContextBuilder(),
            checkpointer=await checkpoint_manager.start(),
            max_steps=settings.agent_max_steps,
            max_tool_calls=settings.agent_max_tool_calls,
        ),
    )
    runner = InProcessTaskRunner(
        session_factory,
        bus,
        runtime_factory,
        default_backend=RuntimeBackend.LANGGRAPH,
        router=RequestRouter(provider),
        agent_registry=agents,
        skill_registry=skills,
        skill_executor=SkillExecutor(provider),
    )

    try:
        async with session_factory() as session:
            service = ConversationService(
                session,
                bus,
                runtime_backend=RuntimeBackend.LANGGRAPH,
            )
            conversation = await service.create(
                user_id=USER_ID,
                title="月度消费报告 Smoke",
            )
            accepted = await service.accept_message(
                conversation_id=conversation.conversation_id,
                user_id=USER_ID,
                content="生成一份2026年8月份消费报告",
            )

        await runner.run(accepted.task_id)

        async with session_factory() as session:
            task = await TaskService(session).get(accepted.task_id, user_id=USER_ID)
            detail = await ConversationService(session, bus).get(
                conversation_id=conversation.conversation_id,
                user_id=USER_ID,
            )
            events = list(
                (
                    await session.execute(
                        select(EventModel)
                        .where(EventModel.task_id == accepted.task_id)
                        .order_by(EventModel.sequence)
                    )
                ).scalars()
            )
        if task.status is not TaskStatus.COMPLETED or task.output is None:
            raise RuntimeError(f"Report task failed: {task.error}")
        report_id = task.output.get("report_id")
        if not isinstance(report_id, str):
            raise TypeError("Task output does not contain a report reference")

        application = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with session_factory() as session:
                yield session

        application.dependency_overrides[get_session] = override_session
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://report-smoke",
        ) as client:
            response = await client.get(f"/api/v1/reports/{report_id}")
        if response.status_code != 200:
            raise RuntimeError(f"GET report failed with {response.status_code}")
        report_payload = response.json()
        content = report_payload["content"]
        golden = json.loads(
            (DATA_DIR / "golden_monthly_report_core.json").read_text(encoding="utf-8")
        )["report_core"]
        actual_core = MonthlySpendingReportCore.model_validate(
            {
                key: value
                for key, value in content.items()
                if key not in {"headline", "insights"}
            }
        ).model_dump(mode="json")
        if actual_core != golden:
            raise RuntimeError("Persisted report core does not match Golden fixture")

        routed = next(event for event in events if event.event_type == "request.routed")
        generated = next(
            event for event in events if event.event_type == "report.generated"
        )
        assistant_messages = [
            message.content
            for message in detail.messages
            if message.role is MessageRole.ASSISTANT
        ]
        if assistant_messages != ["2026年8月消费报告已生成。"]:
            raise RuntimeError("Intermediate agent answer was exposed")
        print("request.routed", routed.data_json)
        print(
            "agent.selected",
            {
                "agent_id": task.output["agent_id"],
                "tools": [
                    {
                        "capability_id": evidence["capability_id"],
                        "input": evidence["input"],
                    }
                    for evidence in task.output["analysis_snapshot"]["tool_evidence"]
                ],
            },
        )
        print(
            "skill.selected",
            {
                "skill_id": task.output["skill_id"],
                "skill_version": task.output["skill_version"],
            },
        )
        print("report.generated", generated.data_json)
        print(
            "report.get",
            {
                "report_id": report_payload["report_id"],
                "period": report_payload["period"],
                "total_spending": content["overview"]["total_spending"],
                "total_spending_display": content["overview"]["total_spending_display"],
                "percentage_change_display": content["period_comparison"][
                    "percentage_change_display"
                ],
                "golden_core_equal": True,
            },
        )
        print("assistant.confirmation", assistant_messages[0])
    finally:
        await checkpoint_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
