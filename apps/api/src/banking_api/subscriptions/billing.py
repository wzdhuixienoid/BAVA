"""Synthetic standing subscription mandates; no real merchant or banking connection."""

import hashlib
from decimal import Decimal

from sqlalchemy import select, text

from banking_api.mock_bank.service import AccountNotFoundError
from banking_api.persistence.models import MockSubscriptionChargeModel, MockSubscriptionStateModel
from banking_api.security.guard import SecurityGuardService, SecurityWriteLockedError
from banking_api.subscriptions.contracts import effective_contracts, next_billing


async def bill_subscription(session, bank, transfer_provider, contract, due, now):
    user_id, subscription_id = contract["user_id"], contract["subscription_id"]
    if session.get_bind().dialect.name == "postgresql":
        digest = hashlib.sha256(f"mock-subscription:{user_id}:{subscription_id}".encode()).digest()
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": int.from_bytes(digest[:8], "big", signed=True)},
        )
    existing = await session.scalar(
        select(MockSubscriptionChargeModel).where(
            MockSubscriptionChargeModel.user_id == user_id,
            MockSubscriptionChargeModel.subscription_id == subscription_id,
            MockSubscriptionChargeModel.billing_at == due,
        )
    )
    if existing:
        return None
    current = next(
        c
        for c in await effective_contracts(bank, session, user_id)
        if c["subscription_id"] == subscription_id
    )
    if current["status"] != "ACTIVE" or current["version"] != contract["version"]:
        return None
    account_id = current.get("source_account_id")
    error = None
    try:
        await SecurityGuardService(session, clock=lambda: now).require_write_allowed(user_id)
    except SecurityWriteLockedError:
        error = "SECURITY_WRITE_LOCKED"
    if not account_id:
        error = error or "SUBSCRIPTION_ACCOUNT_MISSING"
    else:
        await transfer_provider._serialize_source_account(session, account_id, user_id)
        try:
            account = next(
                a for a in bank.list_accounts(user_id=user_id) if a["account_id"] == account_id
            )
            if account["status"] != "ACTIVE" or account["currency"] != current["currency"]:
                error = error or "SUBSCRIPTION_ACCOUNT_INVALID"
            elif await transfer_provider._effective_balance_in_session(
                session, user_id, account_id
            ) < Decimal(current["amount"]):
                error = error or "INSUFFICIENT_FUNDS"
        except (AccountNotFoundError, StopIteration):
            error = error or "SUBSCRIPTION_ACCOUNT_INVALID"
    charge = MockSubscriptionChargeModel(
        user_id=user_id,
        subscription_id=subscription_id,
        source_account_id=account_id,
        merchant=current["merchant"],
        amount=Decimal(current["amount"]),
        currency=current["currency"],
        billing_at=due,
        created_at=now,
        status="FAILED" if error else "SUCCEEDED",
        error_code=error,
    )
    session.add(charge)
    state = await session.get(MockSubscriptionStateModel, (user_id, subscription_id))
    if state is None:
        state = MockSubscriptionStateModel(
            user_id=user_id,
            subscription_id=subscription_id,
            status="ACTIVE",
            version=current["version"],
        )
        session.add(state)
    # Advance even after a failed attempt; never silently retry the same mandate debit.
    original = bank.get_subscription(subscription_id, user_id=user_id)
    state.next_billing_at = next_billing(
        original if original.get("next_billing_at") else current, due
    )
    state.updated_at = now
    state.version += 1
    await session.flush()
    return charge
