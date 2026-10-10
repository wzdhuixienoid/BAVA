"""Shared available balance and stable account serialization for every mock payment."""

import hashlib
import logging
from decimal import Decimal

from sqlalchemy import func, select, text

from banking_api.persistence.models import MockBankTransferModel, MockSubscriptionChargeModel
from banking_api.wealth.models import WealthHold, WealthLedger

logger = logging.getLogger(__name__)


def provider_account_lock_key(source_account_id: str, user_id: str = "dev-user-001") -> int:
    """Map one provider account to a stable signed PostgreSQL advisory-lock key."""

    # Keep the v0.5.2 account-serialization key stable; user scoping is enforced
    # by provider queries and balance calculations, not by changing lock identity.
    digest = hashlib.sha256(
        f"mock-transfer-provider:source-account:{source_account_id}".encode()
    ).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


class AccountBalanceService:
    def __init__(self, session_factory, bank):
        self._session_factory = session_factory
        self._bank = bank

    @staticmethod
    async def serialize(session, source_account_id, user_id="dev-user-001"):
        bind = session.get_bind()
        if bind.dialect.name != "postgresql":
            return
        lock_key = provider_account_lock_key(source_account_id, user_id)
        logger.info("mock provider waiting for account serialization lock_key=%s", lock_key)
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": lock_key},
        )
        logger.info("mock provider account serialization acquired lock_key=%s", lock_key)

    async def effective_balance(self, user_id, account_id):
        async with self._session_factory() as session:
            return await self.in_session(session, user_id, account_id)

    async def in_session(self, session, user_id, account_id):
        base = Decimal(str(self._bank.get_balance(account_id, user_id=user_id)["balance"]))
        debited = (
            await session.execute(
                select(func.coalesce(func.sum(MockBankTransferModel.amount), 0)).where(
                    MockBankTransferModel.source_account_id == account_id,
                    MockBankTransferModel.user_id == user_id,
                    MockBankTransferModel.status.in_(["SUCCEEDED", "PENDING"]),
                )
            )
        ).scalar_one()
        credited = await session.scalar(
            select(func.coalesce(func.sum(MockBankTransferModel.amount), 0)).where(
                MockBankTransferModel.destination_user_id == user_id,
                MockBankTransferModel.destination_account_id == account_id,
                MockBankTransferModel.status == "SUCCEEDED",
                MockBankTransferModel.credited_at.is_not(None),
            )
        )
        subscription_debits = await session.scalar(
            select(func.coalesce(func.sum(MockSubscriptionChargeModel.amount), 0)).where(
                MockSubscriptionChargeModel.user_id == user_id,
                MockSubscriptionChargeModel.source_account_id == account_id,
                MockSubscriptionChargeModel.status == "SUCCEEDED",
            )
        )
        frozen = await session.scalar(
            select(func.coalesce(func.sum(WealthHold.quantity), 0)).where(
                WealthHold.user_id == user_id,
                WealthHold.account_id == account_id,
                WealthHold.kind == "CASH",
                WealthHold.active.is_(True),
            )
        )
        totals = dict(
            (
                await session.execute(
                    select(WealthLedger.action, func.sum(WealthLedger.amount))
                    .where(WealthLedger.user_id == user_id, WealthLedger.account_id == account_id)
                    .group_by(WealthLedger.action)
                )
            ).all()
        )
        wealth = (
            -Decimal(str(frozen))
            - Decimal(str(totals.get("PURCHASE_DEBIT", 0)))
            + Decimal(str(totals.get("REFUND", 0)))
            + Decimal(str(totals.get("REDEEM_CREDIT", 0)))
        )
        return (
            wealth
            + base
            - Decimal(str(debited))
            + Decimal(str(credited))
            - Decimal(str(subscription_debits))
        ).quantize(Decimal("0.01"))
