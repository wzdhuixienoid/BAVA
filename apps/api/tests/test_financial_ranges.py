from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_financial_analysis_agent import build_financial_runtime, financial_request, tool_call

from banking_api.financial.analysis_snapshot import build_financial_analysis_snapshot
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.financial.models import FinancialPeriodInput
from banking_api.financial.request_scope import anomaly_requested, request_scope
from banking_api.llm.models import LLMResponse
from banking_api.mock_bank.service import MockBankService

NOW = datetime(2026, 10, 7, 14, 5, tzinfo=UTC)
START = NOW - timedelta(days=15)
USER = "dev-user-001"


@pytest.mark.parametrize(
    "text", ["分析我最近15天的消费", "分析过去十五天消费", "分析15天的消费", "最近１５天消费"]
)
def test_relative_window_is_grounded(text):
    scope = request_scope(text, NOW)
    assert scope.window == {"start_at": START.isoformat(), "end_at": NOW.isoformat()}
    assert scope.clarification is None


@pytest.mark.parametrize(
    "text",
    [
        "最近0天消费",
        "最近几天消费",
        "最近15天还是20天消费",
        "最近999999999天消费",
    ],
)
def test_unclear_or_invalid_window_requires_clarification(text):
    assert request_scope(text, NOW).clarification


@pytest.mark.parametrize(
    "text", ["最近15天消费", "分析上月消费，不要查异常", "不用异常分析，只分析消费"]
)
def test_ordinary_request_does_not_authorize_anomalies(text):
    assert not anomaly_requested(text)


@pytest.mark.parametrize("text", ["最近15天有没有异常交易", "检查重复扣费", "这些扣款是否可疑"])
def test_explicit_anomaly_request_is_supported(text):
    assert anomaly_requested(text)


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"recent_days": 0},
        {"month": "2026-09", "recent_days": 15},
        {"start_at": START},
        {"start_at": NOW, "end_at": START},
        {"start_at": START.replace(tzinfo=None), "end_at": NOW},
    ],
)
def test_tool_period_validation(arguments):
    with pytest.raises(ValidationError):
        FinancialPeriodInput.model_validate(arguments)


def test_rolling_window_aggregates_with_boundaries_and_user_isolation():
    bank = MockBankService()

    def transaction(key, when, amount, **overrides):
        return dict(
            transaction_id=key,
            occurred_at=when.isoformat(),
            amount=amount,
            account_id="acc_salary",
            user_id=USER,
            direction="DEBIT",
            status="POSTED",
            category="FOOD",
            currency="CNY",
            merchant="商户",
            description="消费",
            **overrides,
        )

    bank._transactions = [
        transaction("start", START, "10"),
        transaction("inside", NOW - timedelta(microseconds=1), "20"),
        transaction("end", NOW, "99"),
        transaction("before", START - timedelta(microseconds=1), "77"),
    ]
    bank._transactions.extend(
        [
            {**transaction("income", START, "100"), "direction": "CREDIT", "category": "SALARY"},
            {**transaction("transfer", START, "800"), "category": "TRANSFER"},
            {**transaction("pending", START, "50"), "status": "PENDING"},
            {**transaction("other-user", START, "999"), "user_id": "other-user"},
        ]
    )
    service = FinancialAnalyticsService(bank)
    period = FinancialPeriodInput(recent_days=15).resolve_period(NOW)
    summary = service.spending_summary(period, user_id=USER)
    assert summary.total_spending == Decimal("30")
    assert summary.total_income == Decimal("100")
    assert summary.spending_transaction_count == 2
    breakdown = service.category_breakdown(period, user_id=USER)
    assert breakdown.categories[0].amount == Decimal("30")
    assert breakdown.categories[0].share_display == "100.00%"
    top = service.top_transactions(period, user_id=USER)
    assert [item.transaction_id for item in top.transactions] == ["inside", "start"]
    assert top.transactions[0].account_display == "工资卡"
    comparison = service.compare_periods(period, user_id=USER)
    assert comparison.previous_spending == Decimal("77")
    assert comparison.absolute_change == Decimal("-47")


async def test_runtime_uses_same_exact_window_even_when_model_chooses_a_month(monkeypatch):
    monkeypatch.setattr("banking_api.runtime.langgraph.graph.reference_now", lambda: NOW)
    runtime, provider = build_financial_runtime(
        [
            tool_call("summary", "get_spending_summary", {"month": "2026-09"}),
            tool_call("categories", "get_category_breakdown", {"recent_days": 30}),
            tool_call("top", "get_top_transactions", {"month": "2026-08", "limit": 3}),
            LLMResponse(content="已按最近十五天的消费区间分析。"),
        ]
    )
    result = await runtime.run(financial_request("分析我最近15天的消费"))
    for item in result.state.successful_tool_results:
        assert datetime.fromisoformat(item.arguments["start_at"]) == START
        assert datetime.fromisoformat(item.arguments["end_at"]) == NOW
        assert "month" not in item.arguments
    periods = {item.output["period"] for item in result.state.successful_tool_results}
    assert periods == {f"{START.isoformat()}/{NOW.isoformat()}"}
    assert "detect_transaction_anomalies" not in {tool.name for tool in provider.requests[0].tools}
    snapshot = build_financial_analysis_snapshot(result.state.successful_tool_results)
    assert snapshot.period == next(iter(periods))


async def test_unrequested_anomaly_call_never_executes_and_model_can_recover(monkeypatch):
    monkeypatch.setattr("banking_api.runtime.langgraph.graph.reference_now", lambda: NOW)
    runtime, provider = build_financial_runtime(
        [
            tool_call("wrong", "detect_transaction_anomalies", {"analysis_days": 15}),
            tool_call("summary", "get_spending_summary", {"recent_days": 15}),
            LLMResponse(content="已分析最近十五天的消费。"),
        ]
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("异常工具不应执行")

    runtime.registry.get_by_name("detect_transaction_anomalies").handler = forbidden
    result = await runtime.run(financial_request("分析我最近15天的消费"))
    assert [item.capability_id for item in result.state.successful_tool_results] == [
        "transaction.spending_summary"
    ]
    assert any(
        "用户没有要求异常交易分析" in message.content
        for message in provider.requests[1].messages
        if message.role == "tool"
    )


async def test_unclear_scope_asks_user_without_tools_or_model():
    runtime, provider = build_financial_runtime([])
    result = await runtime.run(financial_request("分析最近几天的消费"))
    assert "最近多少天" in result.answer
    assert result.state.tool_call_count == 0
    assert provider.requests == []


@pytest.mark.parametrize("days", [1, 120, 366])
def test_arbitrary_day_counts_cross_months_and_years(days):
    scope = request_scope(f"分析最近{days}天消费", NOW)
    assert datetime.fromisoformat(scope.window["start_at"]) == NOW - timedelta(days=days)
    assert FinancialPeriodInput(recent_days=days).resolve_period(NOW) == (
        f"{(NOW - timedelta(days=days)).isoformat()}/{NOW.isoformat()}"
    )


async def test_window_survives_checkpoint_resume_with_a_later_clock(monkeypatch):
    monkeypatch.setattr("banking_api.runtime.langgraph.graph.reference_now", lambda: NOW)
    runtime, _ = build_financial_runtime(
        [
            tool_call("summary", "get_spending_summary", {"recent_days": 15}),
            tool_call("categories", "get_category_breakdown", {"recent_days": 15}),
            LLMResponse(content="已分析相同的十五天消费区间。"),
        ]
    )
    request = financial_request("分析最近15天消费")
    await runtime.run_until_tool_checkpoint(request)
    monkeypatch.setattr(
        "banking_api.runtime.langgraph.graph.reference_now", lambda: NOW + timedelta(days=1)
    )
    result = await runtime.resume(request)
    assert len(result.state.successful_tool_results) == 2
    assert {item.output["period"] for item in result.state.successful_tool_results} == {
        f"{START.isoformat()}/{NOW.isoformat()}"
    }
