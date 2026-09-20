from banking_api.domain.enums import RiskLevel
from banking_api.mock_bank.service import MockBankService
from banking_api.tools.models import BalanceResult, GetBalanceInput, ToolSpec

MINIMAL_BANKING_AGENT_ID = "agent:minimal-banking"


def build_get_balance_tool(bank: MockBankService) -> ToolSpec:
    def handler(arguments: GetBalanceInput) -> BalanceResult:
        return BalanceResult.model_validate(bank.get_balance(arguments.account_id))

    return ToolSpec(
        capability_id="account.get_balance",
        name="get_balance",
        description="根据 account_id 查询单个账户的当前余额。",
        input_model=GetBalanceInput,
        output_model=BalanceResult,
        risk_level=RiskLevel.R1_PRIVATE_READ,
        side_effect=False,
        allowed_callers=frozenset({MINIMAL_BANKING_AGENT_ID}),
        handler=handler,
    )
