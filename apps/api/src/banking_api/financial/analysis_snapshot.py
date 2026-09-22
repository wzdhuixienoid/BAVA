from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from banking_api.financial.models import (
    CategoryBreakdown,
    SpendingPeriodComparison,
    SpendingSummary,
    TopTransactions,
)
from banking_api.runtime.base import SuccessfulToolResult


class ToolEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str
    input: dict[str, Any] = Field(default_factory=dict)


class FinancialAnalysisSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: str | None
    account_ids: list[str]
    spending_summary: SpendingSummary | None = None
    category_breakdown: CategoryBreakdown | None = None
    period_comparison: SpendingPeriodComparison | None = None
    top_transactions: TopTransactions | None = None
    tool_evidence: list[ToolEvidence]


def build_financial_analysis_snapshot(
    results: list[SuccessfulToolResult],
) -> FinancialAnalysisSnapshot:
    period: str | None = None
    account_ids: list[str] = []
    summary = None
    breakdown = None
    comparison = None
    top = None
    evidence: list[ToolEvidence] = []

    for result in results:
        sanitized_input = dict(result.arguments)
        evidence.append(
            ToolEvidence(
                capability_id=result.capability_id,
                input=sanitized_input,
            )
        )
        if result.capability_id.startswith("transaction.") and period is None:
            raw_period = sanitized_input.get("month")
            period = raw_period if isinstance(raw_period, str) else None
            raw_accounts = sanitized_input.get("account_ids")
            if isinstance(raw_accounts, list):
                account_ids = [str(item) for item in raw_accounts]
        if result.capability_id == "transaction.spending_summary":
            summary = SpendingSummary.model_validate(result.output)
        elif result.capability_id == "transaction.category_breakdown":
            breakdown = CategoryBreakdown.model_validate(result.output)
        elif result.capability_id == "transaction.compare_periods":
            comparison = SpendingPeriodComparison.model_validate(result.output)
        elif result.capability_id == "transaction.top_transactions":
            top = TopTransactions.model_validate(result.output)

    return FinancialAnalysisSnapshot(
        period=period,
        account_ids=account_ids,
        spending_summary=summary,
        category_breakdown=breakdown,
        period_comparison=comparison,
        top_transactions=top,
        tool_evidence=evidence,
    )
