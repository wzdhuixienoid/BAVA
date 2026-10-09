from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from banking_api.api.dependencies import get_current_principal
from banking_api.domain.principal import Principal
from banking_api.persistence.models import MockSubscriptionActionModel, SecurityGuardStateModel
from banking_api.subscriptions.provider import (
    MockSubscriptionProvider,
    SubscriptionProviderFaultMode,
)


@pytest.fixture
async def direct_provider(app):
    provider = MockSubscriptionProvider(app.state.test_session_factory, app.state.mock_bank)
    app.state.subscription_provider = provider
    return provider


def action(version=0, key=None):
    return {"confirmed": True, "expected_version": version, "idempotency_key": str(key or uuid4())}


async def test_confirmation_cancels_persistently_and_retries_once(client, app, direct_provider):
    before = (await client.get("/api/v1/subscriptions")).json()
    body = action()
    result = await client.post("/api/v1/subscriptions/sub_video/cancel", json=body)
    assert result.status_code == 200
    assert result.json()["status"] == "CANCELLED"
    assert result.json()["cancellable"] is False
    assert (
        await client.post("/api/v1/subscriptions/sub_video/cancel", json=body)
    ).status_code == 200
    after = (await client.get("/api/v1/subscriptions")).json()
    assert after["monthly_cost_by_currency"] != before["monthly_cost_by_currency"]
    assert all(item["subscription_id"] != "sub_video" for item in after["upcoming_renewals"])
    async with app.state.test_session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(MockSubscriptionActionModel)) == 1
        )
    assert (await client.get("/api/v1/subscriptions/sub_video")).json()["status"] == "CANCELLED"


async def test_rejects_unconfirmed_stale_and_other_users(client, app, direct_provider):
    body = action()
    body["confirmed"] = False
    assert (
        await client.post("/api/v1/subscriptions/sub_video/cancel", json=body)
    ).status_code == 422
    assert (
        await client.post("/api/v1/subscriptions/sub_video/cancel", json=action(99))
    ).status_code == 409
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="another", issuer="test", subject="another"
    )
    try:
        assert (
            await client.post("/api/v1/subscriptions/sub_video/cancel", json=action())
        ).status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_principal)
    assert (await client.get("/api/v1/subscriptions/sub_video")).json()["status"] == "ACTIVE"


async def test_security_lock_blocks_direct_cancellation(client, app, direct_provider):
    async with app.state.test_session_factory() as session:
        session.add(
            SecurityGuardStateModel(
                user_id="dev-user-001",
                locked_until=datetime.now(UTC) + timedelta(minutes=10),
                lock_reason="REAUTH_FAILURES",
            )
        )
        await session.commit()
    result = await client.post("/api/v1/subscriptions/sub_video/cancel", json=action())
    assert result.status_code == 423
    assert (await client.get("/api/v1/subscriptions/sub_video")).json()["status"] == "ACTIVE"


async def test_provider_ambiguous_acceptance_is_reconciled_and_key_cannot_cancel_another(
    client, direct_provider
):
    direct_provider.fault_mode = SubscriptionProviderFaultMode.TIMEOUT_AFTER_ACCEPT
    body = action()
    assert (
        await client.post("/api/v1/subscriptions/sub_video/cancel", json=body)
    ).status_code == 200
    assert (
        await client.post("/api/v1/subscriptions/sub_music/cancel", json=body)
    ).status_code == 409
    assert (await client.get("/api/v1/subscriptions/sub_music")).json()["status"] == "ACTIVE"


async def test_provider_failure_keeps_subscription_active(client, direct_provider):
    direct_provider.fault_mode = SubscriptionProviderFaultMode.DEFINITIVE_FAILURE
    assert (
        await client.post("/api/v1/subscriptions/sub_video/cancel", json=action())
    ).status_code == 502
    assert (await client.get("/api/v1/subscriptions/sub_video")).json()["status"] == "ACTIVE"
