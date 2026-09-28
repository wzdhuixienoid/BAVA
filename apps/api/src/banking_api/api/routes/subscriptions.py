from fastapi import APIRouter, HTTPException, Request

from banking_api.api.dependencies import PrincipalDependency, SessionDependency
from banking_api.subscriptions.models import SubscriptionAnalysisSnapshot, SubscriptionItem
from banking_api.subscriptions.service import (
    SubscriptionAnalysisService,
    SubscriptionNotFoundError,
)

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


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
