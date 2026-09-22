from banking_api.domain.enums import RiskLevel
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.financial.models import FinancialPeriodInput, SpendingPeriodComparison
from banking_api.tools.banking.get_spending_summary import FINANCIAL_ANALYSIS_AGENT_ID
from banking_api.tools.models import ToolSpec


def build_compare_spending_periods_tool(analytics: FinancialAnalyticsService) -> ToolSpec:
    def handler(arguments: FinancialPeriodInput) -> SpendingPeriodComparison:
        return analytics.compare_periods(arguments.month, arguments.account_ids)

    return ToolSpec(
        capability_id="transaction.compare_periods",
        name="compare_spending_periods",
        description="Compare deterministic spending for a month with its previous month.",
        input_model=FinancialPeriodInput,
        output_model=SpendingPeriodComparison,
        risk_level=RiskLevel.R1_PRIVATE_READ,
        side_effect=False,
        allowed_callers=frozenset({FINANCIAL_ANALYSIS_AGENT_ID}),
        handler=handler,
    )
