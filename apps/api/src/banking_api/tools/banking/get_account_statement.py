from banking_api.agents.personal_banking_agent import PERSONAL_BANKING_AGENT_ID
from banking_api.application.account_statement_service import AccountStatementService
from banking_api.config.demo_time import reference_now
from banking_api.domain.enums import RiskLevel
from banking_api.domain.statement import AccountStatementInput, AccountStatementResult
from banking_api.tools.models import ToolExecutionContext, ToolSpec


def build_get_account_statement_tool(bank, session_factory) -> ToolSpec:
    async def handler(
        context: ToolExecutionContext, arguments: AccountStatementInput
    ) -> AccountStatementResult:
        async with session_factory() as session:
            return await AccountStatementService(bank, session).query(
                user_id=context.principal.user_id, arguments=arguments, now=reference_now()
            )

    return ToolSpec(
        capability_id="account.statement",
        name="get_account_statement",
        description=(
            "只读查询本人已入账账单，按时间倒序：转账转出/转入、购物等消费、工资收入、"
            "订阅续费和理财现金流水。支持期间、账户、类别、方向、来源和对手方/备注筛选。"
            "未指定期间默认最近30天；最多50条，使用next_offset及同一as_of继续翻页。"
            "summary提供全部匹配记录的分币种转入/转出合计、按对手方归集、占比及最近一笔，answer提供分析正文；汇总不受分页影响。"
            "查询不会发起转账或推进交易状态；未入账和失败交易不在账单中。"
        ),
        input_model=AccountStatementInput,
        output_model=AccountStatementResult,
        risk_level=RiskLevel.R1_PRIVATE_READ,
        side_effect=False,
        allowed_callers=frozenset({PERSONAL_BANKING_AGENT_ID}),
        handler=handler,
    )
