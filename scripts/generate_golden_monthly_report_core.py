"""One-time generator for the committed v0.3.3 deterministic report core."""

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

DATA_DIR = (
    Path(__file__).parents[1]
    / "apps"
    / "api"
    / "src"
    / "banking_api"
    / "mock_bank"
    / "data"
)


def main() -> None:
    metrics = json.loads(
        (DATA_DIR / "golden_financial_metrics.json").read_text(encoding="utf-8")
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
    core = MonthlySpendingReportSkill().build_core(snapshot)
    fixture = {
        "fixture_version": "0.3.3",
        "source": "golden_financial_metrics.json#2026-08",
        "report_core": core.model_dump(mode="json"),
    }
    print(json.dumps(fixture, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
