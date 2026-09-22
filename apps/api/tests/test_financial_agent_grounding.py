import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver

from banking_api.agents.financial_analysis_agent import FINANCIAL_ANALYSIS_AGENT
from banking_api.context.builder import ContextBuilder
from banking_api.domain.enums import MessageRole
from banking_api.domain.message import Message
from banking_api.financial.analysis_snapshot import build_financial_analysis_snapshot
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.llm.models import LLMResponse, LLMToolCall
from banking_api.mock_bank.service import MockBankService
from banking_api.policy.service import PolicyService
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.runtime.base import AgentRunRequest
from banking_api.runtime.langgraph.graph import LangGraphAgentRuntime
from banking_api.tools.banking import (
    build_compare_spending_periods_tool,
    build_get_category_breakdown_tool,
    build_get_spending_summary_tool,
    build_get_top_transactions_tool,
    build_list_accounts_tool,
)
from banking_api.tools.executor import ToolExecutor

DATA_DIR = Path(__file__).parents[1] / "src/banking_api/mock_bank/data"


def call(call_id: str, name: str, arguments: dict[str, object]) -> LLMResponse:
    return LLMResponse(
        tool_calls=[LLMToolCall(id=call_id, name=name, arguments=arguments)]
    )


async def test_financial_agent_numeric_evidence_matches_committed_golden() -> None:
    golden = json.loads(
        (DATA_DIR / "golden_financial_metrics.json").read_text(encoding="utf-8")
    )
    provider = FakeLLMProvider(
        [
            call("summary", "get_spending_summary", {"month": "2026-08"}),
            call("categories", "get_category_breakdown", {"month": "2026-08"}),
            call("compare", "compare_spending_periods", {"month": "2026-08"}),
            call("top", "get_top_transactions", {"month": "2026-08", "limit": 5}),
            LLMResponse(
                content=(
                    "2026年8月消费为 16,547.30 元，较上月增加 7,214.10 元。"
                    "FOOD、SHOPPING 和 TRAVEL 的变化均以工具结果为准。"
                )
            ),
        ]
    )
    bank = MockBankService()
    analytics = FinancialAnalyticsService(bank)
    registry = ToolRegistry()
    registry.register(build_list_accounts_tool(bank))
    registry.register(build_get_spending_summary_tool(analytics))
    registry.register(build_get_category_breakdown_tool(analytics))
    registry.register(build_compare_spending_periods_tool(analytics))
    registry.register(build_get_top_transactions_tool(analytics))
    runtime = LangGraphAgentRuntime(
        provider=provider,
        registry=registry,
        executor=ToolExecutor(registry, PolicyService()),
        context_builder=ContextBuilder(),
        checkpointer=InMemorySaver(),
    )
    conversation_id = uuid4()
    message = Message(
        message_id=uuid4(),
        conversation_id=conversation_id,
        role=MessageRole.USER,
        content="帮我分析一下2026年8月份为什么花这么多",
        created_at=datetime.now(UTC),
    )

    result = await runtime.run(
        AgentRunRequest(
            task_id=uuid4(),
            conversation_id=conversation_id,
            current_task=message.content,
            conversation_messages=[message],
            authenticated=True,
            agent=FINANCIAL_ANALYSIS_AGENT,
        )
    )
    snapshot = build_financial_analysis_snapshot(
        result.state.successful_tool_results
    ).model_dump(mode="json")

    expected_august = golden["months"]["2026-08"]
    expected_comparison = golden["comparisons"]["2026-07_to_2026-08"]
    assert snapshot["spending_summary"] == expected_august["summary"]
    assert snapshot["category_breakdown"] == expected_august["category_breakdown"]
    assert snapshot["period_comparison"] == expected_comparison
    assert snapshot["top_transactions"] == expected_august["top_transactions"]
    assert snapshot["spending_summary"]["total_spending"] == "16547.30"
    assert snapshot["period_comparison"]["previous_spending"] == "9333.20"
    assert snapshot["period_comparison"]["absolute_change"] == "7214.10"
    changes = {
        item["category"]: item
        for item in snapshot["period_comparison"]["category_changes"]
    }
    assert changes["FOOD"]["absolute_change"] == "589.10"
    assert changes["SHOPPING"]["absolute_change"] == "2662.00"
    assert changes["TRAVEL"]["absolute_change"] == "4260.00"
    assert len(snapshot["top_transactions"]["transactions"]) == 5
    assert len(snapshot["tool_evidence"]) == 4
