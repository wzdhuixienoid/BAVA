from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from banking_api.domain.enums import RiskLevel
from banking_api.persistence.models import OperationModel
from banking_api.tools.models import (
    ToolSpec,
    TransferOperationInput,
    TransferStatusOutput,
)
from banking_api.transfers.provider import TransferProvider

TRANSFER_WORKFLOW_CALLER = "workflow:transfer"


def build_get_transfer_status_tool(
    session_factory: async_sessionmaker[AsyncSession], provider: TransferProvider
) -> ToolSpec:
    async def handler(arguments: TransferOperationInput) -> TransferStatusOutput:
        async with session_factory() as session:
            operation = await session.get(OperationModel, arguments.operation_id)
        if operation is None:
            return TransferStatusOutput(
                status="UNKNOWN",
                error_code="OPERATION_NOT_FOUND",
                error_message="Operation does not exist",
            )
        result = await provider.get_transfer_status(
            idempotency_key=operation.idempotency_key,
            provider_reference=operation.provider_reference,
        )
        return TransferStatusOutput(**result.model_dump())

    return ToolSpec(
        capability_id="transfer.get_status",
        name="get_transfer_status",
        description="查询已持久化 Transfer Operation 的 Provider 最终状态。",
        input_model=TransferOperationInput,
        output_model=TransferStatusOutput,
        risk_level=RiskLevel.R1_PRIVATE_READ,
        side_effect=False,
        allowed_callers=frozenset({TRANSFER_WORKFLOW_CALLER}),
        handler=handler,
    )
