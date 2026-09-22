from banking_api.domain.enums import RiskLevel
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.financial.models import TopTransactions, TopTransactionsInput
from banking_api.tools.banking.get_spending_summary import FINANCIAL_ANALYSIS_AGENT_ID
from banking_api.tools.models import ToolSpec


def build_get_top_transactions_tool(analytics: FinancialAnalyticsService) -> ToolSpec:
    def handler(arguments: TopTransactionsInput) -> TopTransactions:
        return analytics.top_transactions(
            arguments.month,
            arguments.limit,
            arguments.account_ids,
        )

    return ToolSpec(
        capability_id="transaction.top_transactions",
        name="get_top_transactions",
        description="Return a bounded deterministic ranking of monthly spending transactions.",
        input_model=TopTransactionsInput,
        output_model=TopTransactions,
        risk_level=RiskLevel.R1_PRIVATE_READ,
        side_effect=False,
        allowed_callers=frozenset({FINANCIAL_ANALYSIS_AGENT_ID}),
        handler=handler,
    )
