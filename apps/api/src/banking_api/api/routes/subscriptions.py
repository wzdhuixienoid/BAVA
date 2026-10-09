from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from banking_api.api.dependencies import PrincipalDependency, SessionDependency
from banking_api.security.guard import SecurityWriteLockedError
from banking_api.subscriptions.models import SubscriptionAnalysisSnapshot, SubscriptionItem
from banking_api.subscriptions.provider import (
    SubscriptionCancellationRequest,
    SubscriptionProviderAmbiguousError,
)
from banking_api.subscriptions.service import (
    SubscriptionAnalysisService,
    SubscriptionNotFoundError,
)

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


class ConfirmSubscriptionCancellation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: Literal[True]
    expected_version: int = Field(ge=0)
    idempotency_key: UUID


@router.post("/{subscription_id}/cancel", response_model=SubscriptionItem)
async def cancel_subscription(
    subscription_id: str,
    action: ConfirmSubscriptionCancellation,
    request: Request,
    session: SessionDependency,
    principal: PrincipalDependency,
) -> SubscriptionItem:
    provider = request.app.state.subscription_provider
    try:
        result = await provider.cancel(
            SubscriptionCancellationRequest(
                user_id=principal.user_id,
                subscription_id=subscription_id,
                expected_version=action.expected_version,
                idempotency_key=action.idempotency_key,
            ),
            check_security=True,
        )
    except SecurityWriteLockedError as exc:
        raise HTTPException(status_code=423, detail="安全保护已启动，请稍后重试") from exc
    except SubscriptionProviderAmbiguousError:
        result = await provider.get_status(
            user_id=principal.user_id,
            idempotency_key=action.idempotency_key,
            provider_reference=None,
        )
        if result.status != "SUCCEEDED":
            raise HTTPException(status_code=503, detail="取消结果确认中，请稍后重试") from None
    else:
        if result.outcome != "ACCEPTED":
            errors = {
                "SUBSCRIPTION_NOT_FOUND": (404, "未找到该订阅"),
                "SUBSCRIPTION_VERSION_CONFLICT": (409, "订阅已更新，请刷新后再取消"),
                "ALREADY_CANCELLED": (409, "该订阅已取消，请刷新查看"),
                "SUBSCRIPTION_NOT_CANCELLABLE": (422, "该订阅需要前往商户取消"),
                "IDEMPOTENCY_KEY_CONFLICT": (409, "请求已变更，请刷新后重试"),
            }
            code, message = errors.get(result.error_code, (502, "取消未成功，请稍后重试"))
            raise HTTPException(status_code=code, detail=message)
    # The provider has committed the cancellation before the response is returned.
    session.expire_all()
    return await SubscriptionAnalysisService(request.app.state.mock_bank, session).get(
        subscription_id, user_id=principal.user_id
    )


@router.get("", response_model=SubscriptionAnalysisSnapshot)
async def list_subscriptions(
    request: Request,
    session: SessionDependency,
    principal: PrincipalDependency,
    upcoming_days: int = 7,
) -> SubscriptionAnalysisSnapshot:
    return await SubscriptionAnalysisService(request.app.state.mock_bank, session).analyze(
        user_id=principal.user_id,
        upcoming_days=max(1, min(upcoming_days, 90)),
    )


@router.get("/{subscription_id}", response_model=SubscriptionItem)
async def get_subscription(
    subscription_id: str,
    request: Request,
    session: SessionDependency,
    principal: PrincipalDependency,
) -> SubscriptionItem:
    try:
        return await SubscriptionAnalysisService(request.app.state.mock_bank, session).get(
            subscription_id, user_id=principal.user_id
        )
    except SubscriptionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到该订阅") from exc
