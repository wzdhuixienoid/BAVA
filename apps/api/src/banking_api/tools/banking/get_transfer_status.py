from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from banking_api.domain.enums import RiskLevel
from banking_api.domain.operation import OperationType
from banking_api.tools.models import (
    ToolExecutionContext,
    ToolSpec,
    TransferOperationInput,
    TransferStatusOutput,
)
from banking_api.tools.operation_authority import authorized_operation
from banking_api.transfers.provider import TransferProvider

TRANSFER_WORKFLOW_CALLER = "workflow:transfer"


def build_get_transfer_status_tool(
    session_factory: async_sessionmaker[AsyncSession], provider: TransferProvider
) -> ToolSpec:
    async def handler(
        context: ToolExecutionContext, arguments: TransferOperationInput
    ) -> TransferStatusOutput:
        async with session_factory() as session:
            operation = await authorized_operation(
                session,
                arguments.operation_id,
                context.principal.user_id,
                (OperationType.TRANSFER,),
            )
        if operation is None:
            return TransferStatusOutput(
                status="UNKNOWN",
                error_code="OPERATION_NOT_FOUND",
                error_message="Operation does not exist",
            )
        result = await provider.get_transfer_status(
            user_id=operation.user_id,
            idempotency_key=operation.idempotency_key,
            provider_reference=operation.provider_reference,
        )
        return TransferStatusOutput(**result.model_dump())

    return ToolSpec(
        capability_id="transfer.get_status",
        name="get_transfer_status",
        description="对账已授权 Transfer Operation；模拟 Provider 可能完成待确认转账入账。",
        input_model=TransferOperationInput,
        output_model=TransferStatusOutput,
        risk_level=RiskLevel.R3_FINANCIAL_RECONCILE,
        side_effect=True,
        allowed_callers=frozenset({TRANSFER_WORKFLOW_CALLER}),
        handler=handler,
    )
