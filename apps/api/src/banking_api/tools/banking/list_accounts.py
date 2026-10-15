from datetime import UTC, datetime

from banking_api.agents.personal_banking_agent import PERSONAL_BANKING_AGENT_ID
from banking_api.domain.enums import RiskLevel
from banking_api.mock_bank.service import MockBankService
from banking_api.tools.models import (
    ListAccountsInput,
    ListAccountsOutput,
    ToolExecutionContext,
    ToolSpec,
)

TRANSFER_WORKFLOW_CALLER = "workflow:transfer"


def build_list_accounts_tool(bank: MockBankService) -> ToolSpec:
    def handler(context: ToolExecutionContext, _: ListAccountsInput) -> ListAccountsOutput:
        return ListAccountsOutput(
            accounts=bank.list_accounts(user_id=context.principal.user_id),
            as_of=datetime.now(UTC),
        )

    return ToolSpec(
        capability_id="account.list",
        name="list_accounts",
        description="列出当前用户可见的银行账户摘要，不包含余额。",
        input_model=ListAccountsInput,
        output_model=ListAccountsOutput,
        risk_level=RiskLevel.R1_PRIVATE_READ,
        side_effect=False,
        allowed_callers=frozenset(
            {
                PERSONAL_BANKING_AGENT_ID,
                TRANSFER_WORKFLOW_CALLER,
            }
        ),
        handler=handler,
    )
