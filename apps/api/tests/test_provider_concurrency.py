import asyncio
import os
import subprocess
import sys
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import MockBankTransferModel
from banking_api.transfers.mock_provider import (
    MockTransferProvider,
    provider_account_lock_key,
)
from banking_api.transfers.provider import (
    TransferProviderRequest,
    TransferSubmissionOutcome,
)

pytestmark = pytest.mark.postgres
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


class FixedBalanceBank(MockBankService):
    def __init__(self, balances: dict[str, Decimal]) -> None:
        super().__init__()
        self._fixed_balances = balances

    def get_balance(self, account_id: str) -> dict[str, object]:
        return {
            "account_id": account_id,
            "display_name": account_id,
            "masked_number": "****0000",
            "currency": "CNY",
            "balance": self._fixed_balances[account_id],
        }


@pytest.fixture
async def provider_postgres_factory():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not configured")
    assert "test" in TEST_DATABASE_URL.lower(), "TEST_DATABASE_URL must name an isolated test DB"
    engine = create_async_engine(TEST_DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE mock_bank_transfers RESTART IDENTITY"))
    yield factory
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE mock_bank_transfers RESTART IDENTITY"))
    await engine.dispose()


def transfer_request(
    *, account_id: str, amount: str, idempotency_key=None  # type: ignore[no-untyped-def]
) -> TransferProviderRequest:
    return TransferProviderRequest(
        idempotency_key=idempotency_key or uuid4(),
        source_account_id=account_id,
        payee_id="payee_001",
        amount=Decimal(amount),
        currency="CNY",
    )


async def test_different_keys_cannot_overspend_same_account(
    provider_postgres_factory,
) -> None:
    factory = provider_postgres_factory
    bank = FixedBalanceBank({"account_a": Decimal("10000.00")})
    provider_a = MockTransferProvider(factory, bank)
    provider_b = MockTransferProvider(factory, bank)

    results = await asyncio.gather(
        provider_a.submit_transfer(transfer_request(account_id="account_a", amount="8000.00")),
        provider_b.submit_transfer(transfer_request(account_id="account_a", amount="8000.00")),
    )

    assert sorted(result.outcome for result in results) == [
        TransferSubmissionOutcome.ACCEPTED,
        TransferSubmissionOutcome.FAILED,
    ]
    failed = next(
        result
        for result in results
        if result.outcome is TransferSubmissionOutcome.FAILED
    )
    assert failed.error_code == "INSUFFICIENT_FUNDS"
    assert await provider_a.effective_balance("account_a") == Decimal("2000.00")
    async with factory() as session:
        successful_count = await session.scalar(
            select(func.count())
            .select_from(MockBankTransferModel)
            .where(MockBankTransferModel.status == "SUCCEEDED")
        )
        successful_debit = await session.scalar(
            select(func.coalesce(func.sum(MockBankTransferModel.amount), 0)).where(
                MockBankTransferModel.status == "SUCCEEDED"
            )
        )
    assert successful_count == 1
    assert Decimal(str(successful_debit)) == Decimal("8000.00")


async def test_concurrent_transfers_that_exactly_fit_both_succeed(
    provider_postgres_factory,
) -> None:
    factory = provider_postgres_factory
    bank = FixedBalanceBank({"account_a": Decimal("10000.00")})
    provider_a = MockTransferProvider(factory, bank)
    provider_b = MockTransferProvider(factory, bank)
    results = await asyncio.gather(
        provider_a.submit_transfer(transfer_request(account_id="account_a", amount="6000.00")),
        provider_b.submit_transfer(transfer_request(account_id="account_a", amount="4000.00")),
    )
    assert all(result.outcome is TransferSubmissionOutcome.ACCEPTED for result in results)
    assert await provider_a.effective_balance("account_a") == Decimal("0.00")


async def test_concurrent_different_amounts_preserve_nonnegative_balance(
    provider_postgres_factory,
) -> None:
    factory = provider_postgres_factory
    bank = FixedBalanceBank({"account_a": Decimal("10000.00")})
    provider_a = MockTransferProvider(factory, bank)
    provider_b = MockTransferProvider(factory, bank)
    requests = [
        transfer_request(account_id="account_a", amount="8000.00"),
        transfer_request(account_id="account_a", amount="3000.00"),
    ]
    results = await asyncio.gather(
        provider_a.submit_transfer(requests[0]),
        provider_b.submit_transfer(requests[1]),
    )
    accepted_amounts = [
        request.amount
        for request, result in zip(requests, results, strict=True)
        if result.outcome is TransferSubmissionOutcome.ACCEPTED
    ]
    failed = [result for result in results if result.outcome is TransferSubmissionOutcome.FAILED]
    assert len(accepted_amounts) == 1
    assert len(failed) == 1
    assert failed[0].error_code == "INSUFFICIENT_FUNDS"
    assert sum(accepted_amounts, Decimal("0.00")) <= Decimal("10000.00")
    assert await provider_a.effective_balance("account_a") == (
        Decimal("10000.00") - sum(accepted_amounts, Decimal("0.00"))
    )


async def test_different_accounts_are_not_globally_serialized(
    provider_postgres_factory,
) -> None:
    factory = provider_postgres_factory
    bank = FixedBalanceBank(
        {"account_a": Decimal("10000.00"), "account_b": Decimal("10000.00")}
    )
    provider_a = MockTransferProvider(factory, bank)
    provider_b = MockTransferProvider(factory, bank)
    both_balances_read = asyncio.Event()
    arrival_lock = asyncio.Lock()
    arrivals = 0

    def synchronize_balance_read(provider):  # type: ignore[no-untyped-def]
        original = provider._effective_balance_in_session

        async def synchronized(session, account_id):  # type: ignore[no-untyped-def]
            nonlocal arrivals
            balance = await original(session, account_id)
            async with arrival_lock:
                arrivals += 1
                if arrivals == 2:
                    both_balances_read.set()
            await asyncio.wait_for(both_balances_read.wait(), timeout=2)
            return balance

        provider._effective_balance_in_session = synchronized

    synchronize_balance_read(provider_a)
    synchronize_balance_read(provider_b)
    results = await asyncio.gather(
        provider_a.submit_transfer(transfer_request(account_id="account_a", amount="8000.00")),
        provider_b.submit_transfer(transfer_request(account_id="account_b", amount="8000.00")),
    )
    assert all(result.outcome is TransferSubmissionOutcome.ACCEPTED for result in results)
    assert await provider_a.effective_balance("account_a") == Decimal("2000.00")
    assert await provider_b.effective_balance("account_b") == Decimal("2000.00")


async def test_same_key_replay_precedes_current_balance_check(
    provider_postgres_factory,
) -> None:
    factory = provider_postgres_factory
    bank = FixedBalanceBank({"account_a": Decimal("10000.00")})
    provider_a = MockTransferProvider(factory, bank)
    provider_b = MockTransferProvider(factory, bank)
    key = uuid4()
    original = transfer_request(
        account_id="account_a", amount="9000.00", idempotency_key=key
    )
    replays = await asyncio.gather(
        *[
            (provider_a if index % 2 == 0 else provider_b).submit_transfer(original)
            for index in range(10)
        ]
    )
    assert all(result.outcome is TransferSubmissionOutcome.ACCEPTED for result in replays)
    assert len({result.provider_reference for result in replays}) == 1
    assert await provider_a.transfer_count() == 1
    assert await provider_a.effective_balance("account_a") == Decimal("1000.00")

    final_debit = await provider_b.submit_transfer(
        transfer_request(account_id="account_a", amount="1000.00")
    )
    assert final_debit.outcome is TransferSubmissionOutcome.ACCEPTED
    assert await provider_a.effective_balance("account_a") == Decimal("0.00")
    replay_after_balance_changed = await provider_b.submit_transfer(original)
    assert replay_after_balance_changed.outcome is TransferSubmissionOutcome.ACCEPTED
    assert replay_after_balance_changed.provider_reference == replays[0].provider_reference
    assert await provider_a.transfer_count() == 2


async def test_insufficient_funds_fact_is_stable_across_replay(
    provider_postgres_factory,
) -> None:
    factory = provider_postgres_factory
    bank = FixedBalanceBank({"account_a": Decimal("1000.00")})
    provider_a = MockTransferProvider(factory, bank)
    provider_b = MockTransferProvider(factory, bank)
    request = transfer_request(account_id="account_a", amount="2000.00")
    first = await provider_a.submit_transfer(request)
    replay = await provider_b.submit_transfer(request)
    assert first.outcome is TransferSubmissionOutcome.FAILED
    assert replay.outcome is TransferSubmissionOutcome.FAILED
    assert first.error_code == replay.error_code == "INSUFFICIENT_FUNDS"
    assert first.provider_reference == replay.provider_reference
    assert await provider_a.transfer_count() == 1
    assert await provider_a.effective_balance("account_a") == Decimal("1000.00")


def test_advisory_lock_key_is_stable_and_account_scoped() -> None:
    expected = -9144666173027809806
    child_value = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "from banking_api.transfers.mock_provider import provider_account_lock_key; "
            'print(provider_account_lock_key("account_a"))',
        ],
        text=True,
    ).strip()
    assert provider_account_lock_key("account_a") == expected
    assert int(child_value) == expected
    assert provider_account_lock_key("account_a") == provider_account_lock_key("account_a")
    assert provider_account_lock_key("account_a") != provider_account_lock_key("account_b")
