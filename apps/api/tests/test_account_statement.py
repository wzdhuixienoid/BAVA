"""Cash statement reflects actual posting, not notifications, holds or share movements."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_subscription_notifications import runtime as subscription_runtime
from test_wealth import ACCOUNT, USER, assessment, authorize, commit, draft, recover
from test_wealth import wealth as wealth
from test_wealth_repairs import reassemble

from banking_api.api.dependencies import get_current_principal
from banking_api.domain.principal import Principal
from banking_api.persistence.models import (
    MockBankTransferModel,
    MockSubscriptionChargeModel,
    NotificationModel,
)
from banking_api.wealth.models import WealthOrder


async def statement(client, **params):
    response = await client.get("/api/v1/dashboard/transactions", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_completed_wealth_cash_matches_balance_and_pending_has_no_posted_bill(
    wealth, monkeypatch
):
    app, _ = reassemble(wealth, monkeypatch, True)
    factory, clock, balances, *_ = wealth
    import banking_api.api.routes.dashboard as dashboard

    monkeypatch.setattr(dashboard, "reference_now", clock)
    await assessment(wealth)
    before = await balances.effective_balance(USER, ACCOUNT)
    purchase = await commit(
        wealth, await authorize(wealth, await draft(wealth, value="600", pid="mock-wealth-01"))
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await statement(client, category="WEALTH"))["transactions"] == []
        assert await balances.effective_balance(USER, ACCOUNT) == before - Decimal("600")
        async with factory() as session:
            order = await session.scalar(
                select(WealthOrder).where(WealthOrder.operation_id == purchase.operation_id)
            )
            assert order.status == "ACCEPTED"
            clock.now = order.confirm_at.replace(tzinfo=UTC)
        await recover(wealth)
        await recover(wealth)
        page = await statement(client, account_id=ACCOUNT)
        cash = [r for r in page["transactions"] if r["source"] == "WEALTH"]
        assert len([r for r in cash if r["direction"] == "DEBIT"]) == 1
        debit = next(r for r in cash if r["direction"] == "DEBIT")
        assert debit["amount"] == "600.000000"
        assert debit["amount_display"] == "-¥600.00"
        assert "申购" in debit["description"]
        # Mixed sources must not overwrite the requested category or hide each other.
        async with factory() as session:
            session.add(
                MockSubscriptionChargeModel(
                    user_id=USER,
                    subscription_id="mixed-renewal",
                    source_account_id=ACCOUNT,
                    merchant="Mixed subscription",
                    amount=Decimal("15"),
                    currency="CNY",
                    billing_at=clock.now,
                    created_at=clock.now,
                    status="SUCCEEDED",
                )
            )
            await session.commit()
        mixed = (await statement(client))["transactions"]
        assert {"BANK", "WEALTH", "SUBSCRIPTION"} <= {r["source"] for r in mixed}
        only_subscription = (await statement(client, category="SUBSCRIPTION"))["transactions"]
        assert any(r["merchant"] == "Mixed subscription" for r in only_subscription)
        assert all(r["category"] == "SUBSCRIPTION" for r in only_subscription)
        signed = sum(Decimal(r["amount"]) * (1 if r["direction"] == "CREDIT" else -1) for r in cash)
        assert await balances.effective_balance(USER, ACCOUNT) == before + signed - Decimal("15")
        snapshot = (await client.get("/api/v1/dashboard", params={"month": "2026-08"})).json()
        assert debit["transaction_id"] in {
            r["transaction_id"] for r in snapshot["recent_transactions"]
        }
        redeemed = await commit(
            wealth, await authorize(wealth, await draft(wealth, "REDEEM", "10", "mock-wealth-01"))
        )
        async with factory() as session:
            order = await session.scalar(
                select(WealthOrder).where(WealthOrder.operation_id == redeemed.operation_id)
            )
            clock.now = order.confirm_at.replace(tzinfo=UTC)
        await recover(wealth)
        pending_cash = (await statement(client, category="WEALTH"))["transactions"]
        assert not any(r["direction"] == "CREDIT" for r in pending_cash)
        async with factory() as session:
            order = await session.scalar(
                select(WealthOrder).where(WealthOrder.operation_id == redeemed.operation_id)
            )
            clock.now = order.settle_at.replace(tzinfo=UTC)
        await recover(wealth)
        await recover(wealth)
        rows = (await statement(client, category="WEALTH"))["transactions"]
        credits = [r for r in rows if r["direction"] == "CREDIT"]
        assert len(credits) == 1 and credits[0]["amount_display"].startswith("+¥")
        assert "赎回到账" in credits[0]["description"]


@pytest.mark.parametrize("amount,success", [("28", True), ("999999", False)])
async def test_renewal_notice_is_not_a_bill_and_successful_charge_posts_once(
    app, client, monkeypatch, amount, success
):
    import banking_api.api.routes.dashboard as dashboard

    bank, provider, clock, worker = subscription_runtime(app, amount=amount)
    app.state.mock_bank = bank
    app.state.transfer_provider = provider
    monkeypatch.setattr(dashboard, "reference_now", lambda: clock[0])
    before = await provider.effective_balance(USER, ACCOUNT)
    await worker.run_once()
    assert (await statement(client))["transactions"] == []
    clock[0] = datetime(2026, 10, 8, 12, tzinfo=UTC)
    await worker.run_once()
    await worker.run_once()
    rows = (
        await statement(
            client, year=2026, month_number=10, category="SUBSCRIPTION", account_id=ACCOUNT
        )
    )["transactions"]
    assert len(rows) == int(success)
    after = await provider.effective_balance(USER, ACCOUNT)
    assert after == before - (Decimal(amount) if success else 0)
    async with app.state.test_session_factory() as session:
        notices = list(await session.scalars(select(NotificationModel)))
        assert any(n.kind == "SUBSCRIPTION_RENEWAL" for n in notices)
        charge = next(n for n in notices if n.kind == "SUBSCRIPTION_CHARGE")
        assert ("未扣款" in charge.message) is not success
    if success:
        assert rows[0]["amount_display"] == "-¥28.00"
        assert rows[0]["direction"] == "DEBIT"
        assert "已入账" in rows[0]["description"]


async def test_bill_filters_use_beijing_posting_month_and_never_leak_foreign_charges(
    app, client, monkeypatch
):
    import banking_api.api.routes.dashboard as dashboard

    cutoff = datetime(2026, 10, 1, tzinfo=UTC)
    monkeypatch.setattr(dashboard, "reference_now", lambda: cutoff)
    async with app.state.test_session_factory() as session:
        for user, status, delta in [
            (USER, "SUCCEEDED", -1),
            (USER, "FAILED", -2),
            ("another-user", "SUCCEEDED", -3),
            (USER, "SUCCEEDED", 1),
        ]:
            when = cutoff + timedelta(hours=delta)
            session.add(
                MockSubscriptionChargeModel(
                    user_id=user,
                    status=status,
                    subscription_id=f"sub-{user}-{status}-{delta}",
                    source_account_id=ACCOUNT,
                    merchant=f"Merchant-{delta}",
                    amount=Decimal("15"),
                    currency="CNY",
                    billing_at=when,
                    created_at=when,
                )
            )
        await session.commit()
    params = {"year": 2026, "month_number": 10, "category": "SUBSCRIPTION"}
    page = await statement(client, **params, limit=1)
    assert page["total_count"] == 1
    assert page["transactions"][0]["merchant"] == "Merchant--1"
    assert (await statement(client, **params, offset=1))["transactions"] == []
    september = (await statement(client, category="SUBSCRIPTION", month="2026-09"))["transactions"]
    assert not any(row["source"] == "SUBSCRIPTION" for row in september)
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="unrelated-user", issuer="test", subject="unrelated-user"
    )
    assert (await statement(client))["transactions"] == []


async def test_incoming_transfer_requires_actual_credit_and_principal_ownership(app, client):
    when = datetime(2026, 10, 1, tzinfo=UTC)
    async with app.state.test_session_factory() as session:
        for identity, owner, destination, status, credited in [
            ("received", "sender", USER, "SUCCEEDED", True),
            ("uncredited", "sender", USER, "SUCCEEDED", False),
            ("foreign", "sender", "unrelated", "SUCCEEDED", True),
            ("pending", USER, None, "PENDING", False),
            ("failed", USER, None, "FAILED", False),
        ]:
            session.add(
                MockBankTransferModel(
                    provider_reference=identity,
                    idempotency_key=uuid4(),
                    user_id=owner,
                    source_account_id=ACCOUNT,
                    payee_id="payee_001",
                    amount=Decimal("10"),
                    currency="CNY",
                    status=status,
                    destination_user_id=destination,
                    destination_account_id=ACCOUNT if destination else None,
                    credited_at=when if credited else None,
                    created_at=when,
                    applied_at=when,
                )
            )
        await session.commit()
    rows = (await statement(client, category="TRANSFER"))["transactions"]
    transfers = [r for r in rows if r["source"] == "TRANSFER"]
    assert len(transfers) == 1
    assert transfers[0]["transaction_id"] == "transfer:received:credit"
    assert transfers[0]["direction"] == "CREDIT"
    assert transfers[0]["amount_display"] == "+¥10.00"
