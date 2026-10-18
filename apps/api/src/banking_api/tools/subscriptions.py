from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from banking_api.domain.enums import RiskLevel
from banking_api.domain.operation import OperationType
from banking_api.mock_bank.service import MockBankService
from banking_api.subscriptions.models import (
    SubscriptionAnalysisInput,
    SubscriptionListOutput,
    SubscriptionProviderOutput,
)
from banking_api.subscriptions.provider import (
    MockSubscriptionProvider,
    SubscriptionCancellationRequest,
    SubscriptionProviderAmbiguousError,
)
from banking_api.subscriptions.service import SubscriptionAnalysisService
from banking_api.tools.models import ToolExecutionContext, ToolSpec
from banking_api.tools.operation_authority import authorized_operation

SUBSCRIPTION_AGENT_CALLER = "agent:subscription-analysis"
SUBSCRIPTION_WORKFLOW_CALLER = "workflow:subscription-cancel"


class SubscriptionOperationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID


def build_subscription_analyze_tool(
    session_factory: async_sessionmaker[AsyncSession], bank: MockBankService
) -> ToolSpec:
    async def handler(
        context: ToolExecutionContext, arguments: SubscriptionAnalysisInput
    ) -> SubscriptionListOutput:
        async with session_factory() as session:
            from banking_api.security.read_consent import require_subscription_read_consent

            # A trusted workflow may read the contract to prepare its explicit action review.
            # This does not grant the conversational analysis Agent a read consent.
            if getattr(context.principal, "source", None) != "workflow":
                await require_subscription_read_consent(session, context.principal.user_id)
            snapshot = await SubscriptionAnalysisService(bank, session).analyze(
                user_id=context.principal.user_id,
                upcoming_days=arguments.upcoming_days,
            )
            return SubscriptionListOutput(snapshot=snapshot)

    return ToolSpec(
        capability_id="subscription.analyze",
        name="analyze_subscriptions",
        description="返回当前 Principal 的确定性订阅成本、涨价与续费摘要。",
        input_model=SubscriptionAnalysisInput,
        output_model=SubscriptionListOutput,
        risk_level=RiskLevel.R1_PRIVATE_READ,
        side_effect=False,
        allowed_callers=frozenset({SUBSCRIPTION_AGENT_CALLER, SUBSCRIPTION_WORKFLOW_CALLER}),
        handler=handler,
    )


def build_subscription_cancel_tool(
    session_factory: async_sessionmaker[AsyncSession],
    provider: MockSubscriptionProvider,
    *,
    resume: bool = False,
) -> ToolSpec:
    async def handler(
        context: ToolExecutionContext, arguments: SubscriptionOperationInput
    ) -> SubscriptionProviderOutput:
        async with session_factory() as session:
            operation = await authorized_operation(
                session,
                arguments.operation_id,
                context.principal.user_id,
                (
                    OperationType.SUBSCRIPTION_RESUME
                    if resume
                    else OperationType.SUBSCRIPTION_CANCEL,
                ),
            )
        if operation is None:
            return SubscriptionProviderOutput(outcome="FAILED", error_code="OPERATION_NOT_FOUND")
        try:
            result = await (provider.resume if resume else provider.cancel)(
                SubscriptionCancellationRequest(
                    user_id=operation.user_id,
                    subscription_id=str(operation.payload_json["subscription_id"]),
                    idempotency_key=operation.idempotency_key,
                    expected_version=operation.payload_json.get("contract_version"),
                    next_billing_at=operation.payload_json.get("next_billing_at"),
                )
            )
        except SubscriptionProviderAmbiguousError:
            return SubscriptionProviderOutput(outcome="UNKNOWN")
        return SubscriptionProviderOutput(**result.model_dump())

    return ToolSpec(
        capability_id="subscription.resume" if resume else "subscription.cancel",
        name="resume_subscription" if resume else "cancel_subscription",
        description="执行已持久化且已授权的订阅恢复或取消 Operation。",
        input_model=SubscriptionOperationInput,
        output_model=SubscriptionProviderOutput,
        risk_level=RiskLevel.R4_FINANCIAL_COMMIT,
        side_effect=True,
        allowed_callers=frozenset({SUBSCRIPTION_WORKFLOW_CALLER}),
        handler=handler,
    )


def build_subscription_status_tool(
    session_factory: async_sessionmaker[AsyncSession], provider: MockSubscriptionProvider
) -> ToolSpec:
    async def handler(
        context: ToolExecutionContext, arguments: SubscriptionOperationInput
    ) -> SubscriptionProviderOutput:
        async with session_factory() as session:
            operation = await authorized_operation(
                session,
                arguments.operation_id,
                context.principal.user_id,
                (OperationType.SUBSCRIPTION_CANCEL, OperationType.SUBSCRIPTION_RESUME),
            )
        if operation is None:
            return SubscriptionProviderOutput(status="UNKNOWN", error_code="OPERATION_NOT_FOUND")
        result = await provider.get_status(
            user_id=operation.user_id,
            idempotency_key=operation.idempotency_key,
            provider_reference=operation.provider_reference,
        )
        return SubscriptionProviderOutput(**result.model_dump())

    return ToolSpec(
        capability_id="subscription.get_status",
        name="get_subscription_cancellation_status",
        description="查询已持久化订阅管理 Operation 的 Provider 状态。",
        input_model=SubscriptionOperationInput,
        output_model=SubscriptionProviderOutput,
        risk_level=RiskLevel.R1_PRIVATE_READ,
        side_effect=False,
        allowed_callers=frozenset({SUBSCRIPTION_WORKFLOW_CALLER}),
        handler=handler,
    )
