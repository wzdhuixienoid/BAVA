import json
from pathlib import Path

from banking_api.financial.analysis_snapshot import (
    FinancialAnalysisSnapshot,
    ToolEvidence,
)
from banking_api.financial.models import (
    CategoryBreakdown,
    SpendingPeriodComparison,
    SpendingSummary,
    TopTransactions,
)
from banking_api.skills.monthly_spending_report import MonthlySpendingReportSkill

DATA_DIR = Path(__file__).parents[1] / "src/banking_api/mock_bank/data"


def test_monthly_report_core_matches_committed_golden_exactly() -> None:
    metrics = json.loads(
        (DATA_DIR / "golden_financial_metrics.json").read_text(encoding="utf-8")
    )
    expected = json.loads(
        (DATA_DIR / "golden_monthly_report_core.json").read_text(encoding="utf-8")
    )
    august = metrics["months"]["2026-08"]
    snapshot = FinancialAnalysisSnapshot(
        period="2026-08",
        account_ids=[],
        spending_summary=SpendingSummary.model_validate(august["summary"]),
        category_breakdown=CategoryBreakdown.model_validate(
            august["category_breakdown"]
        ),
        period_comparison=SpendingPeriodComparison.model_validate(
            metrics["comparisons"]["2026-07_to_2026-08"]
        ),
        top_transactions=TopTransactions.model_validate(august["top_transactions"]),
        tool_evidence=[
            ToolEvidence(
                capability_id="transaction.spending_summary",
                input={"month": "2026-08"},
            ),
            ToolEvidence(
                capability_id="transaction.category_breakdown",
                input={"month": "2026-08"},
            ),
            ToolEvidence(
                capability_id="transaction.compare_periods",
                input={"month": "2026-08"},
            ),
            ToolEvidence(
                capability_id="transaction.top_transactions",
                input={"month": "2026-08", "limit": 5},
            ),
        ],
    )

    actual = MonthlySpendingReportSkill().build_core(snapshot).model_dump(mode="json")

    assert actual == expected["report_core"]
    assert actual["overview"]["total_spending"] == "16547.30"
    comparison = actual["period_comparison"]
    assert comparison["previous_spending"] == "9333.20"
    assert comparison["absolute_change"] == "7214.10"
    assert comparison["percentage_change_display"] == "+77.3%"
    categories = {item["category"]: item for item in actual["category_breakdown"]}
    assert categories["FOOD"]["absolute_change"] == "589.10"
    assert categories["SHOPPING"]["absolute_change"] == "2662.00"
    assert categories["TRAVEL"]["absolute_change"] == "4260.00"
