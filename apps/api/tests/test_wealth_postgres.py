"""PostgreSQL account serialization, position races and lease recovery in a test DB."""

import asyncio
import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_wealth import ACCOUNT, USER, Clock, assessment, authorize, commit, draft, recover
from test_wealth import test_roundtrip_timeout_conservation_and_security as roundtrip_scenario

from banking_api.application.balance_service import AccountBalanceService
from banking_api.config.settings import get_settings
from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.database import Base
from banking_api.persistence.models import MockSubscriptionChargeModel
from banking_api.policy.service import PolicyService
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.runtime.event_bus import EventBus
from banking_api.tools.executor import ToolExecutor
from banking_api.transfers.mock_provider import MockTransferProvider
from banking_api.transfers.provider import TransferProviderRequest
from banking_api.wealth.catalog import seed_catalog
from banking_api.wealth.models import WealthLedger, WealthOrder, WealthPosition
from banking_api.wealth.provider import MockWealthProvider
from banking_api.wealth.tools import WealthExecutionEngine, build_wealth_tools
from banking_api.wealth.workflow import WealthWorkflow
from banking_api.workflows.transfer.engine import TransferWorkflowEngine

pytestmark = pytest.mark.postgres


@pytest.fixture
async def pg_wealth(monkeypatch):
    url = os.getenv("TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("TEST_DATABASE_URL not configured")
    from sqlalchemy.engine import make_url

    assert "test" in (make_url(url).database or "").lower(), "isolated database required"
    monkeypatch.setenv("MOCK_WEALTH_ENABLED", "true")
    get_settings.cache_clear()
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        await conn.execute(text(f"TRUNCATE {names} CASCADE"))
    clock, bank, bus = Clock(), MockBankService(), EventBus()
    balances = AccountBalanceService(factory, bank)
    provider = MockWealthProvider(factory, balances, clock)
    registry = ToolRegistry()
    for spec in build_wealth_tools(factory, balances, provider):
        registry.register(spec)
    transfer = TransferWorkflowEngine(ToolExecutor(registry, PolicyService()))
    transfer.wealth_engine = WealthExecutionEngine(transfer._executor, balances)
    async with factory() as session:
        await seed_catalog(session)
        await session.commit()
    yield factory, clock, balances, provider, transfer, bus
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {names} CASCADE"))
    await engine.dispose()
    get_settings.cache_clear()


async def prepared(context, workflow):
    factory, clock, balances, *_ = context
    async with factory() as session:
        return await WealthWorkflow(session, balances, clock).prepare(
            workflow.workflow_id, USER, workflow.version
        )


async def test_postgres_roundtrip(pg_wealth):
    await roundtrip_scenario(pg_wealth)


async def test_purchase_transfer_subscription_share_available_balance(pg_wealth):
    factory, clock, balances, provider, _, _ = pg_wealth
    await assessment(pg_wealth)
    initial = await balances.effective_balance(USER, ACCOUNT)
    # Three independent actors each try to debit most of the available balance.
    amount = (initial * Decimal("0.8")).quantize(Decimal("0.01"))
    w = await authorize(pg_wealth, await draft(pg_wealth, value=str(amount), pid="mock-wealth-01"))
    op = await prepared(pg_wealth, w)
    transfer = MockTransferProvider(factory, balances._bank)

    async def subscription_charge():
        async with factory() as session:
            async with session.begin():
                await AccountBalanceService.serialize(session, ACCOUNT, USER)
                funds = await balances.in_session(session, USER, ACCOUNT)
                if funds < amount:
                    return False
                session.add(
                    MockSubscriptionChargeModel(
                        user_id=USER,
                        subscription_id="wealth-race",
                        source_account_id=ACCOUNT,
                        merchant="隔离订阅",
                        amount=amount,
                        currency="CNY",
                        billing_at=clock(),
                        status="SUCCEEDED",
                    )
                )
                return True

    results = await asyncio.gather(
        provider.submit(op.operation_id, USER, "PURCHASE"),
        transfer.submit_transfer(
            TransferProviderRequest(
                user_id=USER,
                idempotency_key=uuid4(),
                source_account_id=ACCOUNT,
                payee_id="payee_001",
                amount=amount,
                currency="CNY",
            )
        ),
        subscription_charge(),
    )
    wins = (
        int(results[0]["outcome"] == "ACCEPTED")
        + int(results[1].outcome == "ACCEPTED")
        + int(results[2])
    )
    assert wins == 1
    assert await balances.effective_balance(USER, ACCOUNT) == initial - amount


async def test_concurrent_purchases_cannot_overspend(pg_wealth):
    _, _, balances, provider, _, _ = pg_wealth
    await assessment(pg_wealth)
    initial = await balances.effective_balance(USER, ACCOUNT)
    amount = (initial * Decimal("0.8")).quantize(Decimal("0.01"))
    ops = []
    for _ in range(2):
        w = await authorize(
            pg_wealth, await draft(pg_wealth, value=str(amount), pid="mock-wealth-01")
        )
        ops.append(await prepared(pg_wealth, w))
    provider2 = MockWealthProvider(provider.session_factory, balances, provider.clock)
    results = await asyncio.gather(
        provider.submit(ops[0].operation_id, USER, "PURCHASE"),
        provider2.submit(ops[1].operation_id, USER, "PURCHASE"),
    )
    assert sorted(r["outcome"] for r in results) == ["ACCEPTED", "FAILED"]
    assert await balances.effective_balance(USER, ACCOUNT) == initial - amount


async def test_concurrent_redeems_and_repeated_credits(pg_wealth):
    factory, clock, balances, provider, _, _ = pg_wealth
    await assessment(pg_wealth)
    await commit(pg_wealth, await authorize(pg_wealth, await draft(pg_wealth)))
    async with factory() as session:
        order = await session.scalar(select(WealthOrder))
        clock.now = order.confirm_at
    await recover(pg_wealth)
    async with factory() as session:
        p = await session.scalar(select(WealthPosition))
        shares = (p.shares * Decimal("0.8")).quantize(Decimal("0.000001"))
    ops = []
    for _ in range(2):
        w = await authorize(pg_wealth, await draft(pg_wealth, "REDEEM", str(shares)))
        ops.append(await prepared(pg_wealth, w))
    provider2 = MockWealthProvider(factory, balances, clock)
    results = await asyncio.gather(
        provider.submit(ops[0].operation_id, USER, "REDEEM"),
        provider2.submit(ops[1].operation_id, USER, "REDEEM"),
    )
    assert sorted(r["outcome"] for r in results) == ["ACCEPTED", "FAILED"]
    async with factory() as session:
        order = await session.scalar(
            select(WealthOrder).where(
                WealthOrder.direction == "REDEEM", WealthOrder.status == "ACCEPTED"
            )
        )
        clock.now = order.settle_at
        oid = order.operation_id
    before = await balances.effective_balance(USER, ACCOUNT)
    await asyncio.gather(provider.query(oid, USER, "REDEEM"), provider2.query(oid, USER, "REDEEM"))
    async with factory() as session:
        order = await session.scalar(select(WealthOrder).where(WealthOrder.operation_id == oid))
        assert order.status == "SETTLED"
        assert await balances.effective_balance(USER, ACCOUNT) == before + Decimal(
            order.actual["net"]
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WealthLedger)
                .where(WealthLedger.action == "REDEEM_CREDIT")
            )
            == 1
        )


async def test_downgrade_refuses_unsubmitted_wealth_draft(pg_wealth):
    import subprocess
    import sys
    from pathlib import Path

    factory, *_ = pg_wealth
    workflow = await draft(pg_wealth, value=None)
    url = os.environ["TEST_DATABASE_URL"]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "0033"],
        cwd=Path(__file__).parents[1],
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Refusing destructive downgrade with wealth workflows" in result.stderr
    async with factory() as session:
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == "0034"
        assert await session.scalar(select(func.count()).select_from(WealthOrder)) == 0
        from banking_api.persistence.models import WorkflowModel

        assert await session.get(WorkflowModel, workflow.workflow_id)


async def test_postgres_disabled_unknown_restart(pg_wealth, monkeypatch):
    from test_wealth_repairs import test_accepted_buy_disable_reassemble_recovers_original

    await test_accepted_buy_disable_reassemble_recovers_original(pg_wealth, monkeypatch, True)


async def test_postgres_disabled_redeem_restart(pg_wealth, monkeypatch):
    from test_wealth_repairs import test_accepted_redeem_disable_restart_confirm_and_credit

    await test_accepted_redeem_disable_restart_confirm_and_credit(pg_wealth, monkeypatch)


async def test_postgres_unaccepted_paused_converges(pg_wealth, monkeypatch):
    from test_wealth_repairs import test_unaccepted_operation_paused_converges_without_holds

    await test_unaccepted_operation_paused_converges_without_holds(pg_wealth, monkeypatch)


async def test_postgres_all_redeem_rechecks_free_snapshot(pg_wealth):
    from test_wealth_repairs import test_all_redeem_free_quantity_snapshot_rechecks_changed_hold

    await test_all_redeem_free_quantity_snapshot_rechecks_changed_hold(pg_wealth)
