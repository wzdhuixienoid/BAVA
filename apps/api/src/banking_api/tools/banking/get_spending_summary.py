from banking_api.agents.financial_analysis_agent import FINANCIAL_ANALYSIS_AGENT_ID
from banking_api.config.demo_time import reference_now
from banking_api.domain.enums import RiskLevel
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.financial.models import FinancialPeriodInput, SpendingSummary
from banking_api.tools.models import ToolExecutionContext, ToolSpec


def build_get_spending_summary_tool(
    analytics: FinancialAnalyticsService, *, bank_reader=None
) -> ToolSpec:
    async def handler(
        context: ToolExecutionContext, arguments: FinancialPeriodInput
    ) -> SpendingSummary:
        source = (
            FinancialAnalyticsService(await bank_reader(context.principal.user_id))
            if bank_reader is not None
            else analytics
        )
        return source.spending_summary(
            arguments.resolve_period(reference_now()),
            arguments.account_ids,
            user_id=context.principal.user_id,
            include_review=arguments.include_review is not False,
        )

    return ToolSpec(
        capability_id="transaction.spending_summary",
        name="get_spending_summary",
        description=(
            "按自然月、自然年、最近任意天数或明确起止时间区间确定性计算收入与消费汇总，"
            "并自动检查同期间同账户范围的值得核对交易，返回简短spending_review；"
            "可选按账户范围筛选。完整异常明细需专门查询。"
        ),
        input_model=FinancialPeriodInput,
        output_model=SpendingSummary,
        risk_level=RiskLevel.R1_PRIVATE_READ,
        side_effect=False,
        allowed_callers=frozenset({FINANCIAL_ANALYSIS_AGENT_ID}),
        handler=handler,
    )
