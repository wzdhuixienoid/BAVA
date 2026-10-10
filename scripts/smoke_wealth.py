"""Deterministic wealth roundtrip in a migrated isolated PostgreSQL test DB only."""

import asyncio
import os
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from banking_api.application.balance_service import AccountBalanceService
from banking_api.application.operation_recovery_policy import OperationRecoveryPolicy
from banking_api.application.operation_service import OperationService
from banking_api.config.settings import Settings, get_settings
from banking_api.domain.enums import OperationStatus, TaskStatus
from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import ConversationModel, TaskModel
from banking_api.persistence.repositories.reauthentications import (
    ReauthenticationRepository,
)
from banking_api.policy.service import PolicyService
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.runtime.event_bus import EventBus
from banking_api.runtime.operation_recovery_worker import OperationRecoveryWorker
from banking_api.tools.executor import ToolExecutor
from banking_api.wealth.calculation import CN, utc
from banking_api.wealth.catalog import seed_catalog
from banking_api.wealth.models import WealthLedger, WealthOrder, WealthPosition
from banking_api.wealth.provider import MockWealthProvider
from banking_api.wealth.schemas import AssessmentInput, RecommendationInput
from banking_api.wealth.service import WealthService
from banking_api.wealth.tools import WealthExecutionEngine, build_wealth_tools
from banking_api.wealth.workflow import WealthWorkflow
from banking_api.workflows.transfer.engine import TransferWorkflowEngine
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def run():
    url = os.environ.get("TEST_DATABASE_URL", "")
    parsed = make_url(url)
    if (
        "test" not in (parsed.database or "").lower()
        or parsed.get_backend_name() != "postgresql"
    ):
        raise ValueError(
            "Smoke requires TEST_DATABASE_URL naming an isolated PostgreSQL test database"
        )
    os.environ["MOCK_WEALTH_ENABLED"] = "true"
    get_settings.cache_clear()
    settings = Settings(
        _env_file=None,
        app_environment="test",
        auth_mode="development",
        mock_wealth_enabled=True,
    )
    # A private injected business clock; never changes Settings, Guard rules or product interfaces.
    times = [datetime(2026, 10, 9, 9, tzinfo=CN)]

    def clock():
        return times[0]

    user = f"wealth-smoke-{uuid4().hex}"
    account = "acc_salary"
    db = create_async_engine(url)
    factory = async_sessionmaker(db, expire_on_commit=False)
    bank = MockBankService(fixture_user_ids=frozenset({user}))
    balances = AccountBalanceService(factory, bank)
    provider = MockWealthProvider(factory, balances, clock)
    registry = ToolRegistry()
    for spec in build_wealth_tools(factory, balances, provider):
        registry.register(spec)
    engine = TransferWorkflowEngine(ToolExecutor(registry, PolicyService()))
    engine.wealth_engine = WealthExecutionEngine(engine._executor, balances)
    bus = EventBus()
    worker = OperationRecoveryWorker(
        factory,
        bus,
        engine,
        clock=clock,
        policy=OperationRecoveryPolicy.from_settings(settings),
        poll_interval_seconds=1,
        batch_size=10,
    )
    async with factory() as session:
        await seed_catalog(session)
        svc = WealthService(session, balances, clock)
        await svc.save_assessment(
            user, AssessmentInput(questionnaire_version="mock-v1", answers=[4] * 8)
        )
        rec = await svc.recommend(
            user, RecommendationInput(needs="稳健", amount="1000", account_id=account)
        )
        assert len(rec.products) == 3
        assert len(await svc.compare([p.product_id for p in rec.products])) == 3
        await session.commit()

    async def authorized(direction, value):
        async with factory() as session:
            c = ConversationModel(user_id=user, title="隔离理财Smoke")
            session.add(c)
            await session.flush()
            task = TaskModel(
                user_id=user,
                conversation_id=c.conversation_id,
                task_type="WEALTH",
                runtime_backend="langgraph",
                status=TaskStatus.WAITING_USER,
                input_json={},
                version=1,
            )
            session.add(task)
            await session.flush()
            from banking_api.security.reauthentication.mock_provider import (
                MockReauthenticationProvider,
            )

            wf = WealthWorkflow(
                session,
                balances,
                clock,
                MockReauthenticationProvider(settings.mock_reauth_code),
            )
            w = await wf.create(
                user,
                c.conversation_id,
                task.task_id,
                {
                    "direction": direction,
                    "product_id": "mock-wealth-03",
                    "account_id": account,
                    "quantity": value,
                },
            )
            await session.commit()
            w = await wf.action(w.workflow_id, user, w.version, "approve")
            w = await wf.action(w.workflow_id, user, w.version, "start-reauth")
            r = await ReauthenticationRepository(session).latest_for_workflow(
                w.workflow_id, user
            )
            w = await wf.action(
                w.workflow_id,
                user,
                w.version,
                "verify-reauth",
                r.reauth_id,
                settings.mock_reauth_code,
            )
            return await OperationService(
                session, bus, engine, clock=clock
            ).commit_workflow(w.workflow_id, user_id=user, expected_version=w.version)

    def restart(enabled):
        nonlocal engine, provider, worker
        from banking_api import main

        os.environ["MOCK_WEALTH_ENABLED"] = str(enabled).lower()
        os.environ["APP_ENVIRONMENT"] = "test"
        os.environ["AUTH_MODE"] = "development"
        os.environ["DEVELOPMENT_USER_ID"] = user
        get_settings.cache_clear()
        main.session_factory = factory
        app = main.create_app()
        provider = app.state.wealth_provider
        provider.clock = clock
        engine = app.state.transfer_workflow_engine
        worker = OperationRecoveryWorker(
            factory,
            bus,
            engine,
            clock=clock,
            policy=OperationRecoveryPolicy.from_settings(settings),
            poll_interval_seconds=1,
            batch_size=10,
        )

    initial = await balances.effective_balance(user, account)
    provider.fault_mode = "TIMEOUT_AFTER_ACCEPT"
    buy = await authorized("PURCHASE", "1000.00")
    assert buy.status == OperationStatus.UNKNOWN
    assert await balances.effective_balance(user, account) == initial - 1000
    restart(False)  # Accepted UNKNOWN survives a disabled, newly assembled application.
    times[0] += timedelta(seconds=10)
    await worker.run_once()
    async with factory() as session:
        order = await session.scalar(
            select(WealthOrder).where(WealthOrder.operation_id == buy.operation_id)
        )
        assert order.status == "ACCEPTED"
        times[0] = utc(order.confirm_at)
    await worker.run_once()
    async with factory() as session:
        order = await session.scalar(
            select(WealthOrder).where(WealthOrder.operation_id == buy.operation_id)
        )
        position = await session.scalar(
            select(WealthPosition).where(WealthPosition.user_id == user)
        )
        assert order.status == "SETTLED" and position.shares == Decimal(
            order.actual["shares"]
        )
        assert await balances.effective_balance(
            user, account
        ) == initial - 1000 + Decimal(order.actual["refund"])
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WealthLedger)
                .where(
                    WealthLedger.order_id == order.order_id,
                    WealthLedger.action == "PURCHASE_DEBIT",
                )
            )
            == 1
        )
    restart(True)
    provider.fault_mode = "SUCCESS"
    sell = await authorized("REDEEM", "10.000000")
    restart(False)  # Redemption must still confirm and credit after disable/restart.
    before = await balances.effective_balance(user, account)
    async with factory() as session:
        order = await session.scalar(
            select(WealthOrder).where(WealthOrder.operation_id == sell.operation_id)
        )
        times[0] = utc(order.confirm_at)
        settle = utc(order.settle_at)
    await worker.run_once()
    assert await balances.effective_balance(user, account) == before
    async with factory() as session:
        order = await session.scalar(
            select(WealthOrder).where(WealthOrder.operation_id == sell.operation_id)
        )
        assert order.status == "CONFIRMED"
        assert (await WealthService(session, balances, clock).positions(user))[
            0
        ].pending_display != "0.00 元"
    times[0] = settle
    await worker.run_once()
    await worker.run_once()
    async with factory() as session:
        order = await session.scalar(
            select(WealthOrder).where(WealthOrder.operation_id == sell.operation_id)
        )
        assert order.status == "SETTLED"
        assert await balances.effective_balance(user, account) == before + Decimal(
            order.actual["net"]
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WealthOrder)
                .where(WealthOrder.user_id == user)
            )
            == 2
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WealthLedger)
                .where(
                    WealthLedger.order_id == order.order_id,
                    WealthLedger.action == "REDEEM_CREDIT",
                )
            )
            == 1
        )
    await db.dispose()
    print(
        "PASS: 测评、推荐、对比、申购授权、超时恢复、成交持仓、部分赎回、待到账、最终到账；申购/赎回受理后关闭开关并重装应用，两订单、零重复扣款。"
    )


if __name__ == "__main__":
    asyncio.run(run())
