from banking_api.agents.financial_analysis_agent import FINANCIAL_ANALYSIS_AGENT_ID
from banking_api.config.demo_time import reference_now
from banking_api.domain.enums import RiskLevel
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.financial.models import TopTransactions, TopTransactionsInput
from banking_api.tools.models import ToolExecutionContext, ToolSpec


def build_get_top_transactions_tool(
    analytics: FinancialAnalyticsService, *, bank_reader=None
) -> ToolSpec:
    async def handler(
        context: ToolExecutionContext, arguments: TopTransactionsInput
    ) -> TopTransactions:
        source = (
            FinancialAnalyticsService(await bank_reader(context.principal.user_id))
            if bank_reader is not None
            else analytics
        )
        return source.top_transactions(
            arguments.resolve_period(reference_now()),
            arguments.limit,
            arguments.account_ids,
            user_id=context.principal.user_id,
        )

    return ToolSpec(
        capability_id="transaction.top_transactions",
        name="get_top_transactions",
        description=(
            "返回指定期间（自然月、自然年或任意时间区间）金额最高的消费交易，"
            "结果按金额确定性排序，最多 20 条。"
        ),
        input_model=TopTransactionsInput,
        output_model=TopTransactions,
        risk_level=RiskLevel.R1_PRIVATE_READ,
        side_effect=False,
        allowed_callers=frozenset({FINANCIAL_ANALYSIS_AGENT_ID}),
        handler=handler,
    )
