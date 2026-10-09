from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import (
    MockSubscriptionChargeModel,
    MockSubscriptionStateModel,
    NotificationModel,
)
from banking_api.runtime.subscription_notification_worker import SubscriptionNotificationWorker
from banking_api.subscriptions.provider import (
    MockSubscriptionProvider,
    SubscriptionCancellationRequest,
)
from banking_api.transfers.mock_provider import MockTransferProvider


def runtime(app, *, due=None, amount="28.00", billing_enabled=True):
    bank = MockBankService()
    bank._subscriptions = [dict(bank._subscriptions[0], amount=amount)]
    if due:
        bank._subscriptions[0]["next_billing_at"] = due.isoformat()
    bank._transactions = []
    provider = MockTransferProvider(app.state.test_session_factory, bank)
    clock = [datetime(2026, 10, 1, 12, tzinfo=UTC)]
    worker = SubscriptionNotificationWorker(
        app.state.test_session_factory,
        bank,
        transfer_provider=provider,
        billing_enabled=billing_enabled,
        clock=lambda: clock[0],
    )
    return bank, provider, clock, worker


async def test_seven_day_reminder_and_charge_once_per_period_and_restart(app):
    bank, provider, clock, worker = runtime(app)
    due = datetime(2026, 10, 8, 12, tzinfo=UTC)
    clock[0] = due - timedelta(days=7, seconds=1)
    before = await provider.effective_balance("dev-user-001", "acc_salary")
    assert await worker.run_once() == 0
    clock[0] += timedelta(seconds=1)
    assert await worker.run_once() == 1
    assert await worker.run_once() == 0
    assert await provider.effective_balance("dev-user-001", "acc_salary") == before
    clock[0] = due
    assert await worker.run_once() == 1
    assert await worker.run_once() == 0
    assert await provider.effective_balance("dev-user-001", "acc_salary") == before - Decimal("28")
    async with app.state.test_session_factory() as session:
        rows = (await session.scalars(select(NotificationModel))).all()
        assert {r.kind for r in rows} == {"SUBSCRIPTION_RENEWAL", "SUBSCRIPTION_CHARGE"}
        assert len(rows) == 2
        for row in rows:
            row.read_at, row.deleted_at = clock[0], clock[0]
        await session.commit()
    restarted = SubscriptionNotificationWorker(
        app.state.test_session_factory,
        bank,
        transfer_provider=provider,
        billing_enabled=True,
        clock=lambda: clock[0],
    )
    assert await restarted.run_once() == 0
    clock[0] = datetime(2026, 11, 1, 12, tzinfo=UTC)
    assert await restarted.run_once() == 1
    clock[0] = datetime(2026, 11, 8, 12, tzinfo=UTC)
    assert await restarted.run_once() == 1
    assert await provider.effective_balance("dev-user-001", "acc_salary") == before - Decimal("56")


async def test_cancel_stops_renewal_and_debit(app):
    from uuid import uuid4

    bank, provider, clock, worker = runtime(app)
    assert await worker.run_once() == 1
    await MockSubscriptionProvider(app.state.test_session_factory, bank).cancel(
        SubscriptionCancellationRequest(
            user_id="dev-user-001", subscription_id="sub_video", idempotency_key=uuid4()
        )
    )
    clock[0] = datetime(2026, 10, 8, 12, tzinfo=UTC)
    before = await provider.effective_balance("dev-user-001", "acc_salary")
    assert await worker.run_once() == 0
    async with app.state.test_session_factory() as session:
        assert (await session.scalars(select(MockSubscriptionChargeModel))).all() == []
    assert await provider.effective_balance("dev-user-001", "acc_salary") == before


async def test_insufficient_balance_notifies_without_debit_or_retry(app):
    _, provider, clock, worker = runtime(app, amount="999999.00")
    await worker.run_once()
    before = await provider.effective_balance("dev-user-001", "acc_salary")
    clock[0] = datetime(2026, 10, 8, 12, tzinfo=UTC)
    assert await worker.run_once() == 1
    assert await worker.run_once() == 0
    async with app.state.test_session_factory() as session:
        charge = await session.scalar(select(MockSubscriptionChargeModel))
        assert charge.status == "FAILED" and charge.error_code == "INSUFFICIENT_FUNDS"
        state = await session.get(MockSubscriptionStateModel, ("dev-user-001", "sub_video"))
        assert state.next_billing_at.month == 11
        alert = await session.scalar(
            select(NotificationModel).where(NotificationModel.kind == "SUBSCRIPTION_CHARGE")
        )
        assert "失败" in alert.title and "未扣款" in alert.message
    assert await provider.effective_balance("dev-user-001", "acc_salary") == before


async def test_startup_skips_historic_debits_and_new_posted_transaction_notifies_once(app):
    bank, _, clock, worker = runtime(app, billing_enabled=False)
    old = {
        "transaction_id": "old",
        "merchant": "星幕视频",
        "currency": "CNY",
        "amount": "28",
        "occurred_at": "2026-09-08T12:00:00Z",
        "status": "POSTED",
        "direction": "DEBIT",
        "category": "SUBSCRIPTION",
    }
    bank._transactions = [dict(old, user_id="dev-user-001")]
    await worker.run_once()
    bank._transactions.append(dict(old, transaction_id="new", user_id="dev-user-001"))
    assert await worker.run_once() == 1
    assert await worker.run_once() == 0
    async with app.state.test_session_factory() as session:
        rows = (
            await session.scalars(
                select(NotificationModel).where(NotificationModel.kind == "SUBSCRIPTION_CHARGE")
            )
        ).all()
        assert len(rows) == 1 and "已入账" in rows[0].title


@pytest.mark.parametrize(
    "interval,expected", [("MONTHLY", (2027, 3, 31)), ("ANNUAL", (2028, 1, 31))]
)
async def test_calendar_anchor_and_annual_billing(app, interval, expected):
    due = datetime(2027, 1, 31, 12, tzinfo=UTC)
    bank, _, clock, worker = runtime(app, due=due)
    bank._subscriptions[0]["billing_interval"] = interval
    clock[0] = due - timedelta(days=7)
    await worker.run_once()
    clock[0] = due
    assert await worker.run_once() == 1
    if interval == "MONTHLY":
        clock[0] = datetime(2027, 2, 28, 12, tzinfo=UTC)
        await worker.run_once()
    async with app.state.test_session_factory() as session:
        state = await session.get(MockSubscriptionStateModel, ("dev-user-001", "sub_video"))
        assert (
            state.next_billing_at.year,
            state.next_billing_at.month,
            state.next_billing_at.day,
        ) == expected


async def test_security_lock_stops_debit(app):
    from banking_api.persistence.models import SecurityGuardStateModel

    _, provider, clock, worker = runtime(app)
    await worker.run_once()
    before = await provider.effective_balance("dev-user-001", "acc_salary")
    clock[0] = datetime(2026, 10, 8, 12, tzinfo=UTC)
    async with app.state.test_session_factory() as session:
        session.add(
            SecurityGuardStateModel(
                user_id="dev-user-001",
                locked_until=clock[0] + timedelta(days=1),
                lock_reason="CONTROL_BYPASS",
            )
        )
        await session.commit()
    await worker.run_once()
    async with app.state.test_session_factory() as session:
        charge = await session.scalar(select(MockSubscriptionChargeModel))
        assert charge.status == "FAILED" and charge.error_code == "SECURITY_WRITE_LOCKED"
    assert await provider.effective_balance("dev-user-001", "acc_salary") == before


async def test_owners_are_independent_and_initial_start_never_back_charges(app):
    bank = MockBankService(fixture_user_ids=frozenset({"owner-a", "owner-b"}))
    bank._subscriptions = [c for c in bank._subscriptions if c["subscription_id"] == "sub_video"]
    bank._transactions = []
    provider = MockTransferProvider(app.state.test_session_factory, bank)
    clock = [datetime(2026, 10, 9, 12, tzinfo=UTC)]
    worker = SubscriptionNotificationWorker(
        app.state.test_session_factory,
        bank,
        transfer_provider=provider,
        billing_enabled=True,
        clock=lambda: clock[0],
    )
    assert await worker.run_once() == 0
    clock[0] = datetime(2026, 11, 1, 12, tzinfo=UTC)
    assert await worker.run_once() == 2
    clock[0] = datetime(2026, 11, 8, 12, tzinfo=UTC)
    assert await worker.run_once() == 2
    async with app.state.test_session_factory() as session:
        charges = (await session.scalars(select(MockSubscriptionChargeModel))).all()
        assert len(charges) == 2 and {c.user_id for c in charges} == {"owner-a", "owner-b"}
    assert await provider.effective_balance(
        "owner-a", "acc_salary"
    ) == await provider.effective_balance("owner-b", "acc_salary")
