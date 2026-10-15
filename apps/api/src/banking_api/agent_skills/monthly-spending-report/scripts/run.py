"""Read a validated snapshot from stdin and emit report core JSON; no model call."""

import sys

from pydantic import ValidationError

from banking_api.financial.analysis_snapshot import FinancialAnalysisSnapshot
from banking_api.skills.monthly_spending_report import MonthlySpendingReportSkill, ReportInputError


def main():
    try:
        snapshot = FinancialAnalysisSnapshot.model_validate_json(sys.stdin.read())
        result = MonthlySpendingReportSkill().build_core(snapshot)
    except (ValidationError, ReportInputError) as exc:
        print(f"Invalid report snapshot: {exc}", file=sys.stderr)
        return 2
    print(result.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
