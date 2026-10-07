from banking_api.domain.enums import RiskLevel
from banking_api.mock_bank.service import MockBankService
from banking_api.payees.service import PayeeService
from banking_api.tools.models import (
    ListPayeesInput,
    ListPayeesOutput,
    SearchPayeesInput,
    SearchPayeesOutput,
    ToolExecutionContext,
    ToolSpec,
)

TRANSFER_WORKFLOW_CALLER = "workflow:transfer"
BANKING_AGENT_CALLER = "agent:minimal-banking"


def build_search_payees_tool(bank: MockBankService, session_factory=None) -> ToolSpec:
    async def handler(
        context: ToolExecutionContext, arguments: SearchPayeesInput
    ) -> SearchPayeesOutput:
        if session_factory is None:
            return SearchPayeesOutput(
                payees=bank.search_payees(arguments.query, user_id=context.principal.user_id)
            )
        async with session_factory() as session:
            return SearchPayeesOutput(
                payees=await PayeeService(bank, session).search(
                    arguments.query, user_id=context.principal.user_id
                )
            )

    return ToolSpec(
        capability_id="payee.search",
        name="search_payees",
        description="按姓名或别名精确查找最多 10 个当前用户的收款人。",
        input_model=SearchPayeesInput,
        output_model=SearchPayeesOutput,
        risk_level=RiskLevel.R1_PRIVATE_READ,
        side_effect=False,
        allowed_callers=frozenset({TRANSFER_WORKFLOW_CALLER, BANKING_AGENT_CALLER}),
        handler=handler,
    )


def build_list_payees_tool(bank: MockBankService, session_factory=None) -> ToolSpec:
    async def handler(
        context: ToolExecutionContext, arguments: ListPayeesInput
    ) -> ListPayeesOutput:
        if session_factory is None:
            return ListPayeesOutput(
                payees=bank.list_payees(user_id=context.principal.user_id)[
                    arguments.offset : arguments.offset + 100
                ]
            )
        async with session_factory() as session:
            return ListPayeesOutput(
                payees=await PayeeService(bank, session).list(
                    user_id=context.principal.user_id, offset=arguments.offset
                )
            )

    return ToolSpec(
        capability_id="payee.list",
        name="list_payees",
        description="查询当前用户可转账的收款人（每页最多100项）。",
        input_model=ListPayeesInput,
        output_model=ListPayeesOutput,
        risk_level=RiskLevel.R1_PRIVATE_READ,
        side_effect=False,
        allowed_callers=frozenset({BANKING_AGENT_CALLER}),
        handler=handler,
    )
