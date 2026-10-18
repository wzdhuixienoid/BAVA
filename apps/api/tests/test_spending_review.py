from datetime import UTC, datetime, timedelta

from test_financial_analysis_agent import build_financial_runtime, financial_request, tool_call
from test_transaction_anomalies import FixtureBank, baseline, transaction

from banking_api.financial.analysis_snapshot import FinancialAnalysisSnapshot, ToolEvidence
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.financial.anomaly_detector import TransactionAnomalyDetector
from banking_api.financial.anomaly_models import TransactionAnomalyType
from banking_api.llm.models import LLMResponse
from banking_api.mock_bank.service import MockBankService
from banking_api.skills.monthly_spending_report import MonthlySpendingReportSkill
from banking_api.skills.transaction_anomaly_analysis import TransactionAnomalyAnalysisSkill

NOW = datetime(2026, 10, 7, 15, 5, tzinfo=UTC)


def test_stable_monthly_rent_is_not_compared_with_small_shopping():
    rent = [
        transaction(f"rent-{days}", NOW - timedelta(days=days), "公寓", "6200", category="HOUSING")
        for days in [61, 31, 1]
    ]
    snapshot = TransactionAnomalyDetector(FixtureBank({"a": baseline(NOW) + rent})).detect(
        user_id="a", generated_at=NOW
    )
    assert not any(item.transaction_id.startswith("rent") for item in snapshot.anomalies)


def test_monthly_bill_jump_is_still_detected():
    rent = [
        transaction(f"rent-{days}", NOW - timedelta(days=days), "公寓", amount, category="HOUSING")
        for days, amount in [(61, "6200"), (31, "6200"), (1, "9300")]
    ]
    snapshot = TransactionAnomalyDetector(FixtureBank({"a": rent})).detect(
        user_id="a", generated_at=NOW
    )
    assert snapshot.anomalies[0].transaction_id == "rent-1"
    evidence = snapshot.anomalies[0].evidence[TransactionAnomalyType.AMOUNT_SPIKE]
    assert evidence.baseline_scope == "同商户周期支出"
    assert str(evidence.ratio) == "1.5"


def test_category_cold_start_does_not_use_unrelated_purchases_as_baseline():
    rows = baseline(NOW) + [
        transaction("medical", NOW - timedelta(days=1), "医院", "9000", category="HEALTH")
    ]
    snapshot = TransactionAnomalyDetector(FixtureBank({"a": rows})).detect(
        user_id="a", generated_at=NOW
    )
    assert not any(item.transaction_id == "medical" for item in snapshot.anomalies)
    assert snapshot.baseline_skipped_count > 0


def test_same_merchant_history_takes_priority_over_category_baseline():
    rows = baseline(NOW) + [
        transaction(f"merchant-{index}", NOW - timedelta(days=10 - index), "大家电", "2000")
        for index in range(3)
    ]
    rows.append(transaction("current", NOW - timedelta(days=1), "大家电", "2100"))
    snapshot = TransactionAnomalyDetector(FixtureBank({"a": rows})).detect(
        user_id="a", generated_at=NOW
    )
    assert not any(item.transaction_id == "current" for item in snapshot.anomalies)


def test_review_is_brief_and_duplicates_take_priority():
    rows = baseline(NOW) + [
        transaction(f"large-{index}", NOW - timedelta(days=index + 1), f"新商户-{index}", "900")
        for index in range(5)
    ]
    rows += [
        transaction(f"duplicate-{index}", NOW - timedelta(minutes=9 - index * 3), "重复商户", "500")
        for index in range(3)
    ]
    snapshot = TransactionAnomalyDetector(FixtureBank({"a": rows})).detect(
        user_id="a", generated_at=NOW
    )
    review = TransactionAnomalyAnalysisSkill().review(snapshot)
    assert len(review.items) == 3
    assert review.items[0].transaction_id == "duplicate-2"
    assert "短时重复扣款" in review.items[0].reason
    assert "仅列出优先核对" in review.answer
    assert "| 日期 |" not in review.answer
    assert "不代表已确认欺诈" in review.answer


def test_selected_account_and_owner_scope_apply_to_checks():
    rows = baseline(NOW) + [transaction("other-card", NOW - timedelta(days=1), "其他卡商户", "900")]
    for row in rows:
        row["account_id"] = "other-card"
    rows.append(
        {
            **transaction("selected", NOW - timedelta(days=1), "日常消费", "20"),
            "account_id": "selected",
        }
    )
    detector = TransactionAnomalyDetector(FixtureBank({"a": rows, "b": baseline(NOW)}))
    snapshot = detector.detect(user_id="a", generated_at=NOW, account_ids=["selected"])
    assert snapshot.analyzed_transaction_count == 1
    assert snapshot.anomalies == []
    assert (
        detector.detect(
            user_id="b", generated_at=NOW, account_ids=["selected"]
        ).analyzed_transaction_count
        == 0
    )


async def test_ordinary_spending_gets_one_brief_skill_review_without_extra_tool_calls():
    runtime, _ = build_financial_runtime(
        [
            tool_call("summary", "get_spending_summary", {"month": "2026-09"}),
            LLMResponse(content="本月消费情况。"),
        ]
    )
    result = await runtime.run(financial_request("分析2026年9月消费"))
    assert "消费支出：" in result.answer
    assert result.answer.count("### 值得核对的交易") == 1
    assert result.state.tool_call_count == 1
    assert all(
        item.capability_id != "transaction.detect_anomalies"
        for item in result.state.successful_tool_results
    )


async def test_explicit_opt_out_skips_automatic_check():
    runtime, _ = build_financial_runtime(
        [
            tool_call("summary", "get_spending_summary", {"month": "2026-09"}),
            LLMResponse(content="本月消费情况。"),
        ]
    )
    result = await runtime.run(financial_request("分析2026年9月消费，不要异常分析"))
    assert "消费支出：" in result.answer and "值得核对的交易" not in result.answer
    assert result.state.successful_tool_results[0].output["spending_review"] is None


def test_report_core_persists_review_from_summary_and_legacy_core_remains_readable():
    analytics = FinancialAnalyticsService(MockBankService())
    summary = analytics.spending_summary("2026-09", user_id="dev-user-001")
    snapshot = FinancialAnalysisSnapshot(
        period="2026-09",
        account_ids=[],
        spending_summary=summary,
        category_breakdown=analytics.category_breakdown("2026-09", user_id="dev-user-001"),
        tool_evidence=[
            ToolEvidence(capability_id=cap, input={"month": "2026-09"})
            for cap in ["transaction.spending_summary", "transaction.category_breakdown"]
        ],
    )
    core = MonthlySpendingReportSkill().build_core(snapshot)
    assert core.spending_review == summary.spending_review
    assert core.spending_review is not None
    assert "值得核对的交易" in core.model_dump(mode="json")["spending_review"]["answer"]


def test_spending_still_works_when_check_exceeds_one_year():
    analytics = FinancialAnalyticsService(MockBankService())
    summary = analytics.spending_summary(
        "2025-01-01T00:00:00Z/2026-10-07T00:00:00Z", user_id="dev-user-001"
    )
    assert summary.total_spending > 0
    assert summary.spending_review.status == "UNAVAILABLE"
    assert "超过一年" in summary.spending_review.message
