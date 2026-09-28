from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from banking_api.domain.enums import RiskLevel
from banking_api.persistence.models import OperationModel
from banking_api.tools.models import (
    ToolExecutionContext,
    ToolSpec,
    TransferCommitOutput,
    TransferOperationInput,
)
from banking_api.transfers.provider import (
    TransferProvider,
    TransferProviderAmbiguousError,
    TransferProviderRequest,
)

TRANSFER_WORKFLOW_CALLER = "workflow:transfer"


def build_commit_transfer_tool(
    session_factory: async_sessionmaker[AsyncSession], provider: TransferProvider
) -> ToolSpec:
    async def handler(
        context: ToolExecutionContext, arguments: TransferOperationInput
    ) -> TransferCommitOutput:
        async with session_factory() as session:
            result = await session.execute(
                select(OperationModel).where(
                    OperationModel.operation_id == arguments.operation_id,
                    OperationModel.user_id == context.principal.user_id,
                )
            )
            operation = result.scalar_one_or_none()
        if operation is None:
            return TransferCommitOutput(
                outcome="FAILED",
                error_code="OPERATION_NOT_FOUND",
                error_message="Operation does not exist",
            )
        payload = operation.payload_json
        request = TransferProviderRequest(
            user_id=operation.user_id,
            idempotency_key=operation.idempotency_key,
            source_account_id=payload["source_account_id"],
            payee_id=payload["payee_id"],
            amount=payload["amount"],
            currency=payload["currency"],
        )
        try:
            result = await provider.submit_transfer(request)
        except TransferProviderAmbiguousError:
            return TransferCommitOutput(outcome="UNKNOWN")
        return TransferCommitOutput(**result.model_dump())

    return ToolSpec(
        capability_id="transfer.commit",
        name="commit_transfer",
        description="提交已持久化且已授权的 Transfer Operation。",
        input_model=TransferOperationInput,
        output_model=TransferCommitOutput,
        risk_level=RiskLevel.R4_FINANCIAL_COMMIT,
        side_effect=True,
        allowed_callers=frozenset({TRANSFER_WORKFLOW_CALLER}),
        handler=handler,
    )
