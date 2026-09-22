from banking_api.agents.financial_analysis_agent import FINANCIAL_ANALYSIS_AGENT_ID
from banking_api.domain.enums import RiskLevel
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.financial.models import FinancialPeriodInput, SpendingSummary
from banking_api.tools.models import ToolSpec


def build_get_spending_summary_tool(analytics: FinancialAnalyticsService) -> ToolSpec:
    def handler(arguments: FinancialPeriodInput) -> SpendingSummary:
        return analytics.spending_summary(arguments.month, arguments.account_ids)

    return ToolSpec(
        capability_id="transaction.spending_summary",
        name="get_spending_summary",
        description=(
            "按自然月确定性计算收入与消费汇总，返回总金额、交易笔数和币种；"
            "可选按账户范围筛选。"
        ),
        input_model=FinancialPeriodInput,
        output_model=SpendingSummary,
        risk_level=RiskLevel.R1_PRIVATE_READ,
        side_effect=False,
        allowed_callers=frozenset({FINANCIAL_ANALYSIS_AGENT_ID}),
        handler=handler,
    )
