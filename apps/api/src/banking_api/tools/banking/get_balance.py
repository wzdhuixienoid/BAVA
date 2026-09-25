from collections.abc import Awaitable, Callable
from decimal import Decimal

from banking_api.domain.enums import RiskLevel
from banking_api.mock_bank.service import MockBankService
from banking_api.tools.models import BalanceResult, GetBalanceInput, ToolSpec

MINIMAL_BANKING_AGENT_ID = "agent:minimal-banking"
TRANSFER_WORKFLOW_CALLER = "workflow:transfer"


def build_get_balance_tool(
    bank: MockBankService,
    effective_balance_reader: Callable[[str], Awaitable[Decimal]] | None = None,
) -> ToolSpec:
    async def handler(arguments: GetBalanceInput) -> BalanceResult:
        result = bank.get_balance(arguments.account_id)
        if effective_balance_reader is not None:
            result["balance"] = await effective_balance_reader(arguments.account_id)
        return BalanceResult.model_validate(result)

    return ToolSpec(
        capability_id="account.get_balance",
        name="get_balance",
        description="根据 account_id 查询单个账户的当前余额。",
        input_model=GetBalanceInput,
        output_model=BalanceResult,
        risk_level=RiskLevel.R1_PRIVATE_READ,
        side_effect=False,
        allowed_callers=frozenset({MINIMAL_BANKING_AGENT_ID, TRANSFER_WORKFLOW_CALLER}),
        handler=handler,
    )
