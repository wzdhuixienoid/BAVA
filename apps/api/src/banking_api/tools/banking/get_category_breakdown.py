from banking_api.agents.financial_analysis_agent import FINANCIAL_ANALYSIS_AGENT_ID
from banking_api.domain.enums import RiskLevel
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.financial.models import CategoryBreakdown, FinancialPeriodInput
from banking_api.tools.models import ToolExecutionContext, ToolSpec


def build_get_category_breakdown_tool(analytics: FinancialAnalyticsService) -> ToolSpec:
    def handler(
        context: ToolExecutionContext, arguments: FinancialPeriodInput
    ) -> CategoryBreakdown:
        return analytics.category_breakdown(
            arguments.month,
            arguments.account_ids,
            user_id=context.principal.user_id,
        )

    return ToolSpec(
        capability_id="transaction.category_breakdown",
        name="get_category_breakdown",
        description=("按自然月或自然年确定性汇总各消费分类的金额、交易笔数和占比，并按金额降序返回。"),
        input_model=FinancialPeriodInput,
        output_model=CategoryBreakdown,
        risk_level=RiskLevel.R1_PRIVATE_READ,
        side_effect=False,
        allowed_callers=frozenset({FINANCIAL_ANALYSIS_AGENT_ID}),
        handler=handler,
    )
