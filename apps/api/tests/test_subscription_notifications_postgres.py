# ruff: noqa: F811
import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_postgres_integration import postgres_factory  # noqa: F401
from test_subscription_notifications import runtime

from banking_api.persistence.models import MockSubscriptionChargeModel, NotificationModel
from banking_api.runtime.subscription_notification_worker import SubscriptionNotificationWorker
from banking_api.transfers.provider import TransferProviderRequest

pytestmark = pytest.mark.postgres


async def test_two_workers_and_transfer_share_account_balance(app, postgres_factory):
    app.state.test_session_factory = postgres_factory
    bank, provider, clock, first = runtime(app, amount="20000.00")
    await first.run_once()
    second = SubscriptionNotificationWorker(
        postgres_factory,
        bank,
        transfer_provider=provider,
        billing_enabled=True,
        clock=lambda: clock[0],
    )
    before = await provider.effective_balance("dev-user-001", "acc_salary")
    clock[0] = datetime(2026, 10, 8, 12, tzinfo=UTC)
    await asyncio.gather(
        first.run_once(),
        second.run_once(),
        provider.submit_transfer(
            TransferProviderRequest(
                user_id="dev-user-001",
                source_account_id="acc_salary",
                payee_id="payee_003",
                amount=Decimal("10000"),
                currency="CNY",
                idempotency_key=uuid4(),
            )
        ),
    )
    after = await provider.effective_balance("dev-user-001", "acc_salary")
    assert after in {before - Decimal("20000"), before - Decimal("10000")}
    assert after >= 0
    async with postgres_factory() as session:
        charges = (await session.scalars(select(MockSubscriptionChargeModel))).all()
        notices = (
            await session.scalars(
                select(NotificationModel).where(NotificationModel.kind == "SUBSCRIPTION_CHARGE")
            )
        ).all()
        assert len(charges) == len(notices) == 1
    assert await first.run_once() == 0
