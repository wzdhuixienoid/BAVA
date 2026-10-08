from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from test_financial_analysis_agent import build_financial_runtime, financial_request, tool_call
from test_transaction_anomalies import FixtureBank, baseline, transaction

from banking_api.financial.anomaly_detector import TransactionAnomalyDetector
from banking_api.financial.anomaly_models import TransactionAnomalyInput
from banking_api.financial.request_scope import request_scope
from banking_api.llm.models import LLMResponse
from banking_api.skills.transaction_anomaly_analysis import TransactionAnomalyAnalysisSkill

NOW = datetime(2026, 10, 7, 15, 5, tzinfo=UTC)


def sample_snapshot():
    rows = baseline(NOW) + [transaction("spike", NOW - timedelta(days=1), "测试商户", "8600.00")]
    return TransactionAnomalyDetector(FixtureBank({"a": rows})).detect(
        user_id="a", generated_at=NOW
    )


def test_skill_formats_one_grounded_chinese_answer():
    snapshot = sample_snapshot()
    before = snapshot.model_dump(mode="json")
    answer = TransactionAnomalyAnalysisSkill().execute(snapshot).answer
    assert "异常交易分析" in answer
    assert "8600.00" in answer
    assert "| 高 |" in answer
    assert "| 86.00 |" in answer  # Synthetic baseline median is 100.
    assert "金额（元）" in answer
    assert "币种" not in answer and "人民币" not in answer
    assert not any(token in answer for token in ["¥", "HIGH", "MEDIUM", "AMOUNT_SPIKE"])
    assert snapshot.model_dump(mode="json") == before
    assert TransactionAnomalyAnalysisSkill.definition.allowed_tools == ()


def test_long_window_includes_transactions_older_than_ninety_days():
    early = NOW - timedelta(days=200)
    rows = baseline(early) + [
        transaction("old-spike", early - timedelta(days=1), "历史商户", "900.00")
    ]
    rows += baseline(NOW) + [transaction("new-spike", NOW - timedelta(days=1), "新商户", "900.00")]
    detector = TransactionAnomalyDetector(FixtureBank({"a": rows}))
    snapshot = detector.detect(user_id="a", generated_at=NOW, analysis_days=365)
    assert {item.transaction_id for item in snapshot.anomalies} >= {"old-spike", "new-spike"}
    assert snapshot.baseline_lookback_days == 90
    assert snapshot.analysis_period_started_at == NOW - timedelta(days=365)
    assert TransactionAnomalyInput(analysis_days=365).bounds(NOW)[0] == NOW - timedelta(days=365)


def test_year_scope_handles_leap_day_and_is_calendar_year():
    scope = request_scope("近一年有什么异常交易吗", NOW)
    assert datetime.fromisoformat(scope.window["start_at"]) == NOW.replace(year=2025)
    leap = datetime(2024, 2, 29, tzinfo=UTC)
    assert datetime.fromisoformat(
        request_scope("最近一年消费", leap).window["start_at"]
    ) == leap.replace(year=2023, day=28)


async def test_runtime_does_not_silently_shorten_year_and_uses_skill(monkeypatch):
    monkeypatch.setattr("banking_api.runtime.langgraph.graph.reference_now", lambda: NOW)
    runtime, _ = build_financial_runtime(
        [
            tool_call("anomalies", "detect_transaction_anomalies", {"analysis_days": 90}),
            LLMResponse(content="错误声称只能查90天，所有交易都正常。"),
        ]
    )
    events = []

    async def sink(kind, data):
        events.append((kind, data))

    from dataclasses import replace

    request = replace(financial_request("近一年有什么异常交易吗"), event_sink=sink)
    result = await runtime.run(request)
    output = result.state.successful_tool_results[0]
    assert datetime.fromisoformat(output.arguments["start_at"]) == NOW.replace(year=2025)
    assert "analysis_days" not in output.arguments
    assert "只能查90天" not in result.answer
    assert "所有交易都正常" not in result.answer
    assert "2025年10月07日" in result.answer
    assert any(
        kind == "skill.run.completed" and data["skill_id"] == "skill:transaction-anomaly-analysis"
        for kind, data in events
    )


def test_result_truncation_and_missing_data_are_explicit():
    snapshot = sample_snapshot()
    truncated = snapshot.model_copy(update={"truncated": True, "total_anomaly_count": 75})
    answer = TransactionAnomalyAnalysisSkill().execute(truncated).answer
    assert "75 笔" in answer and "以下展示最近" in answer
    empty = TransactionAnomalyDetector(FixtureBank({})).detect(
        user_id="a", generated_at=NOW, analysis_days=365
    )
    assert "没有可分析的已入账消费记录" in TransactionAnomalyAnalysisSkill().execute(empty).answer
    shorter_data = snapshot.model_copy(
        update={"available_data_started_at": NOW - timedelta(days=10)}
    )
    assert "更早部分没有交易证据" in TransactionAnomalyAnalysisSkill().execute(shorter_data).answer


def test_skill_ratio_rounding_does_not_change_evidence():
    snapshot = sample_snapshot()
    evidence = next(iter(snapshot.anomalies[0].evidence.values()))
    evidence.ratio = Decimal("1.005")
    answer = TransactionAnomalyAnalysisSkill().execute(snapshot).answer
    assert "| 1.01 |" in answer
    assert evidence.ratio == Decimal("1.005")


async def test_requests_over_one_year_require_clarification_without_running_tools():
    runtime, provider = build_financial_runtime([])
    result = await runtime.run(financial_request("近两年有什么异常交易吗"))
    assert "最多支持一年" in result.answer
    assert result.state.tool_call_count == 0
    assert provider.requests == []


def test_one_year_limit_applies_to_day_and_explicit_range_arguments():
    from pydantic import ValidationError

    from banking_api.financial.errors import FinancialDomainError

    with pytest.raises(ValidationError):
        TransactionAnomalyInput(analysis_days=500)
    with pytest.raises(FinancialDomainError, match="最多支持一年"):
        TransactionAnomalyInput(analysis_days=366).bounds(NOW)
    with pytest.raises(FinancialDomainError, match="最多支持一年"):
        TransactionAnomalyInput(start_at=NOW - timedelta(days=500), end_at=NOW).bounds(NOW)
    assert TransactionAnomalyInput(analysis_days=366).bounds(datetime(2024, 3, 1, tzinfo=UTC))[
        0
    ] == datetime(2023, 3, 1, tzinfo=UTC)


async def test_explicit_historical_dates_are_used_instead_of_recent_default(monkeypatch):
    monkeypatch.setattr("banking_api.runtime.langgraph.graph.reference_now", lambda: NOW)
    runtime, _ = build_financial_runtime(
        [
            tool_call("anomalies", "detect_transaction_anomalies", {"analysis_days": 30}),
            LLMResponse(content="错误地分析了最近三十天。"),
        ]
    )
    result = await runtime.run(financial_request("分析2025年8月1日至2025年8月31日的异常交易"))
    arguments = result.state.successful_tool_results[0].arguments
    assert arguments["start_at"] == "2025-08-01T00:00:00+08:00"
    assert arguments["end_at"] == "2025-09-01T00:00:00+08:00"
    assert "2025年08月01日" in result.answer
    assert "2025年09月01日" in result.answer
    assert "最近三十天" not in result.answer


async def test_oversized_explicit_range_is_not_shortened_or_executed():
    runtime, provider = build_financial_runtime([])
    result = await runtime.run(financial_request("查询2024-01-01到2025-12-31的异常交易"))
    assert "最多支持一年" in result.answer
    assert result.state.tool_call_count == 0 and not provider.requests


def test_explicit_clock_range_and_incomplete_dates():
    scope = request_scope("分析2025-08-01 10:30至2025-08-02 15:00的异常交易", NOW)
    assert scope.window == {
        "start_at": "2025-08-01T10:30:00+08:00",
        "end_at": "2025-08-02T15:00:00+08:00",
    }
    assert request_scope("从2025年8月1日起的异常交易", NOW).clarification
    assert request_scope("2025年2月30日的异常交易", NOW).clarification


def test_no_records_for_requested_period_is_reported_with_available_data():
    snapshot = TransactionAnomalyDetector(FixtureBank({"a": baseline(NOW)})).detect(
        user_id="a",
        generated_at=NOW,
        analysis_started_at=datetime(2023, 1, 1, tzinfo=UTC),
        analysis_ended_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    assert not snapshot.anomalies
    answer = TransactionAnomalyAnalysisSkill().execute(snapshot).answer
    assert "该区间没有可分析的已入账消费记录" in answer
    assert "可用交易记录" in answer


def test_historical_subscription_price_increase_is_not_lost_when_later_prices_stay_flat():
    rows = [
        transaction("s1", NOW - timedelta(days=150), "星幕视频", "30.00", category="SUBSCRIPTION"),
        transaction("s2", NOW - timedelta(days=120), "星幕视频", "45.00", category="SUBSCRIPTION"),
        transaction("s3", NOW - timedelta(days=90), "星幕视频", "45.00", category="SUBSCRIPTION"),
    ]
    snapshot = TransactionAnomalyDetector(FixtureBank({"a": rows})).detect(
        user_id="a", generated_at=NOW, analysis_days=365
    )
    assert any(
        item.transaction_id == "s2"
        and any(rule.value == "SUBSCRIPTION_PRICE_SPIKE" for rule in item.anomaly_types)
        for item in snapshot.anomalies
    )


def test_duplicate_evidence_can_cross_start_boundary_but_result_stays_inside_requested_range():
    start = NOW - timedelta(days=15)
    rows = [
        transaction("before", start - timedelta(minutes=2), "同一商户", "100.00"),
        transaction("inside", start + timedelta(minutes=2), "同一商户", "100.00"),
    ]
    snapshot = TransactionAnomalyDetector(FixtureBank({"a": rows})).detect(
        user_id="a", generated_at=NOW, analysis_days=15
    )
    assert [item.transaction_id for item in snapshot.anomalies] == ["inside"]
    assert snapshot.analyzed_transaction_count == 1
