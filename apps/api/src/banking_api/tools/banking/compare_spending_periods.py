from banking_api.agents.financial_analysis_agent import FINANCIAL_ANALYSIS_AGENT_ID
from banking_api.config.demo_time import reference_now
from banking_api.domain.enums import RiskLevel
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.financial.models import FinancialPeriodInput, SpendingPeriodComparison
from banking_api.tools.models import ToolExecutionContext, ToolSpec


def build_compare_spending_periods_tool(
    analytics: FinancialAnalyticsService, *, bank_reader=None
) -> ToolSpec:
    async def handler(
        context: ToolExecutionContext, arguments: FinancialPeriodInput
    ) -> SpendingPeriodComparison:
        source = (
            FinancialAnalyticsService(await bank_reader(context.principal.user_id))
            if bank_reader is not None
            else analytics
        )
        return source.compare_periods(
            arguments.resolve_period(reference_now()),
            arguments.account_ids,
            user_id=context.principal.user_id,
        )

    return ToolSpec(
        capability_id="transaction.compare_periods",
        name="compare_spending_periods",
        description=(
            "将指定自然月与上月、自然年与上年、或任意区间与紧邻的等长前期进行确定性比较，返回总额及分类的"
            "绝对变化和百分比变化。"
        ),
        input_model=FinancialPeriodInput,
        output_model=SpendingPeriodComparison,
        risk_level=RiskLevel.R1_PRIVATE_READ,
        side_effect=False,
        allowed_callers=frozenset({FINANCIAL_ANALYSIS_AGENT_ID}),
        handler=handler,
    )
