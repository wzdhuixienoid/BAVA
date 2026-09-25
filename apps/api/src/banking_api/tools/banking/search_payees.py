from banking_api.domain.enums import RiskLevel
from banking_api.mock_bank.service import MockBankService
from banking_api.tools.models import SearchPayeesInput, SearchPayeesOutput, ToolSpec

TRANSFER_WORKFLOW_CALLER = "workflow:transfer"


def build_search_payees_tool(bank: MockBankService) -> ToolSpec:
    def handler(arguments: SearchPayeesInput) -> SearchPayeesOutput:
        return SearchPayeesOutput(payees=bank.search_payees(arguments.query))

    return ToolSpec(
        capability_id="payee.search",
        name="search_payees",
        description="按姓名或手机别名精确查找最多 10 个收款人。",
        input_model=SearchPayeesInput,
        output_model=SearchPayeesOutput,
        risk_level=RiskLevel.R1_PRIVATE_READ,
        side_effect=False,
        allowed_callers=frozenset({TRANSFER_WORKFLOW_CALLER}),
        handler=handler,
    )
