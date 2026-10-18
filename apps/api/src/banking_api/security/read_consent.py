from datetime import UTC, datetime, timedelta

from banking_api.audit.domain import record_action
from banking_api.config.settings import get_settings
from banking_api.persistence.models import SubscriptionReadConsentModel
from banking_api.security.exceptions import SubscriptionReadConsentRequired
from banking_api.security.guard import acquire_security_user_lock


async def require_subscription_read_consent(session, user_id, *, clock=lambda: datetime.now(UTC)):
    row = await session.get(SubscriptionReadConsentModel, user_id)
    now = clock()
    if row is None or row.expires_at.replace(tzinfo=UTC) <= now:
        raise SubscriptionReadConsentRequired("请先确认读取订阅、费用和续费安排（授权5分钟）。")


async def approve_subscription_read(session, user_id, *, clock=lambda: datetime.now(UTC)):
    await acquire_security_user_lock(session, user_id)
    now = clock()
    expiry = now + timedelta(seconds=get_settings().subscription_read_consent_seconds)
    row = await session.get(SubscriptionReadConsentModel, user_id)
    if row is None:
        row = SubscriptionReadConsentModel(user_id=user_id, approved_at=now, expires_at=expiry)
        session.add(row)
    else:
        row.approved_at, row.expires_at = now, expiry
    await record_action(
        session,
        user_id=user_id,
        action="subscription.read.confirm",
        resource_id=user_id,
        payload={"capability": "subscription.analyze", "expires_at": expiry.isoformat()},
        outcome="APPROVED",
        evidence=[{"stage": "user_confirmation", "confirmed": True, "risk_level": "YELLOW"}],
    )
    return expiry
