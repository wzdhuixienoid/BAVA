from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal

from banking_api.agents.personal_banking_agent import PERSONAL_BANKING_AGENT_ID
from banking_api.domain.account import AccountBalanceResult
from banking_api.domain.enums import RiskLevel
from banking_api.mock_bank.service import MockBankService
from banking_api.tools.models import (
    GetBalanceInput,
    ToolExecutionContext,
    ToolSpec,
)

TRANSFER_WORKFLOW_CALLER = "workflow:transfer"


def build_get_balance_tool(
    bank: MockBankService,
    effective_balance_reader: Callable[[str, str], Awaitable[Decimal]] | None = None,
) -> ToolSpec:
    async def handler(
        context: ToolExecutionContext, arguments: GetBalanceInput
    ) -> AccountBalanceResult:
        user_id = context.principal.user_id
        result = bank.get_balance(arguments.account_id, user_id=user_id)
        if effective_balance_reader is not None:
            result["balance"] = await effective_balance_reader(user_id, arguments.account_id)
        return AccountBalanceResult(**result, as_of=datetime.now(UTC))

    return ToolSpec(
        capability_id="account.get_balance",
        name="get_balance",
        description="根据 account_id 查询单个账户的当前余额。",
        input_model=GetBalanceInput,
        output_model=AccountBalanceResult,
        risk_level=RiskLevel.R1_PRIVATE_READ,
        side_effect=False,
        allowed_callers=frozenset({PERSONAL_BANKING_AGENT_ID, TRANSFER_WORKFLOW_CALLER}),
        handler=handler,
    )
