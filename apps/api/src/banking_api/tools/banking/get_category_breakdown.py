from banking_api.domain.enums import RiskLevel
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.financial.models import CategoryBreakdown, FinancialPeriodInput
from banking_api.tools.banking.get_spending_summary import FINANCIAL_ANALYSIS_AGENT_ID
from banking_api.tools.models import ToolSpec


def build_get_category_breakdown_tool(analytics: FinancialAnalyticsService) -> ToolSpec:
    def handler(arguments: FinancialPeriodInput) -> CategoryBreakdown:
        return analytics.category_breakdown(arguments.month, arguments.account_ids)

    return ToolSpec(
        capability_id="transaction.category_breakdown",
        name="get_category_breakdown",
        description="Calculate a deterministic monthly spending breakdown by category.",
        input_model=FinancialPeriodInput,
        output_model=CategoryBreakdown,
        risk_level=RiskLevel.R1_PRIVATE_READ,
        side_effect=False,
        allowed_callers=frozenset({FINANCIAL_ANALYSIS_AGENT_ID}),
        handler=handler,
    )
