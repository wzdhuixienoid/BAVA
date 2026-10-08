from datetime import UTC, datetime, timedelta

import pytest
from test_financial_analysis_agent import build_financial_runtime, financial_request, tool_call

from banking_api.financial.request_scope import request_scope
from banking_api.llm.models import LLMResponse

NOW = datetime(2026, 10, 7, 15, 5, tzinfo=UTC)


@pytest.mark.parametrize(
    "text", ["我最近有什么消费", "近期消费情况", "分析这段时间的支出", "最近的账单怎么样"]
)
def test_unspecified_recent_spending_defaults_to_thirty_days(text):
    scope = request_scope(text, NOW)
    assert scope.clarification is None
    assert scope.window == {
        "start_at": (NOW - timedelta(days=30)).isoformat(),
        "end_at": NOW.isoformat(),
    }


def test_explicit_spending_scope_is_not_replaced_with_default():
    assert request_scope("最近15天消费", NOW).window["start_at"] == (
        NOW - timedelta(days=15)
    ).isoformat()
    assert request_scope("最近2026年9月消费", NOW).window is None
    assert request_scope("最近三个月的消费", NOW).window is None
    assert request_scope("最近多少天的消费", NOW).clarification
    assert request_scope("2026年9月1日至9月15日消费", NOW).window == {
        "start_at": "2026-09-01T00:00:00+08:00",
        "end_at": "2026-09-16T00:00:00+08:00",
    }


async def test_runtime_uses_thirty_days_even_if_model_picks_last_month(monkeypatch):
    monkeypatch.setattr("banking_api.runtime.langgraph.graph.reference_now", lambda: NOW)
    runtime, _ = build_financial_runtime(
        [
            tool_call("summary", "get_spending_summary", {"month": "2026-09"}),
            LLMResponse(content="已汇总近30天消费。"),
        ]
    )
    result = await runtime.run(financial_request("我最近有什么消费"))
    arguments = result.state.successful_tool_results[0].arguments
    assert set(arguments) == {"start_at", "end_at"}
    assert datetime.fromisoformat(arguments["start_at"]) == NOW - timedelta(days=30)
    assert datetime.fromisoformat(arguments["end_at"]) == NOW
