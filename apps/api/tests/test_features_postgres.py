# ruff: noqa: F811
"""Run only against an explicitly named independent PostgreSQL test database."""

import asyncio
import os
import sys
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select
from test_aa_collections import aa_runtime, pay, published_request
from test_postgres_integration import postgres_factory  # noqa: F401
from test_scheduled_transfers import (
    create_schedule,
    schedule_enabled,  # noqa: F401
)
from test_transfer_operations import operation_runtime

from banking_api.application.aa_service import AAService
from banking_api.application.schedule_service import ScheduleService
from banking_api.persistence.models import (
    OperationModel,
    ScheduledTransferModel,
)
from banking_api.runtime.schedule_worker import ScheduleWorker


@pytest.fixture
async def pg_app(app, postgres_factory):
    app.state.test_session_factory = postgres_factory
    return app


async def scheduled(app):
    _, provider, _, engine = operation_runtime(app)
    engine.mock_scheduling_supported = True
    ready = await create_schedule(app, engine)
    async with app.state.test_session_factory() as session:
        resource = await ScheduleService(session, engine).authorize(
            UUID(ready.state["draft"]["schedule_id"]), ready.user_id, ready.version
        )
    return provider, engine, ready, resource


@pytest.mark.parametrize("monthly", [False, True])
async def test_schedule_two_processes_one_operation(pg_app, schedule_enabled, monthly):
    if monthly:
        from test_recurring_transfers import recurring

        _, provider, _, engine = operation_runtime(pg_app)
        ready, resource, _ = await recurring(pg_app, engine)
    else:
        provider, engine, ready, resource = await scheduled(pg_app)
    now = resource.scheduled_for + timedelta(seconds=1)
    code = """import asyncio
from datetime import datetime
from banking_api.main import app
from banking_api.persistence.database import session_factory
from banking_api.runtime.schedule_worker import ScheduleWorker
async def run():
    worker = ScheduleWorker(session_factory,app.state.event_bus,
        app.state.transfer_workflow_engine,clock=lambda:datetime.fromisoformat(NOW))
    await worker.run_once()
asyncio.run(run())
""".replace("NOW", repr(now.isoformat()))
    env = {
        **os.environ,
        "DATABASE_URL": os.environ["TEST_DATABASE_URL"],
        "AUTH_MODE": "development",
        "MOCK_SCHEDULED_TRANSFERS_ENABLED": "true",
    }
    processes = [
        await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            code,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        for _ in range(2)
    ]
    outputs = await asyncio.gather(*(p.communicate() for p in processes))
    assert all(p.returncode == 0 for p in processes), outputs
    async with pg_app.state.test_session_factory() as session:
        result = await ScheduleService(session, engine).get(resource.schedule_id, ready.user_id)
        assert result.status == "SUCCEEDED"
        assert await session.scalar(select(func.count()).select_from(OperationModel)) == 1
    assert await provider.transfer_count() == 1


async def test_schedule_lease_restart_and_cancel_race(pg_app, schedule_enabled):
    provider, engine, ready, resource = await scheduled(pg_app)
    now = resource.scheduled_for + timedelta(seconds=1)
    async with pg_app.state.test_session_factory() as session:
        row = await session.get(ScheduledTransferModel, resource.schedule_id)
        row.status, row.lease_owner, row.lease_expires_at = (
            "EXECUTING",
            "dead-process",
            now - timedelta(seconds=1),
        )
        await session.commit()

    async def cancel():
        async with pg_app.state.test_session_factory() as session:
            try:
                row = await ScheduleService(session, engine).get(
                    resource.schedule_id, ready.user_id
                )
                return await ScheduleService(session, engine).cancel(
                    resource.schedule_id, ready.user_id, row.version
                )
            except Exception:
                return None

    worker = ScheduleWorker(
        pg_app.state.test_session_factory, pg_app.state.event_bus, engine, clock=lambda: now
    )
    cancelled, _ = await asyncio.gather(cancel(), worker.run_once())
    async with pg_app.state.test_session_factory() as session:
        result = await ScheduleService(session, engine).get(resource.schedule_id, ready.user_id)
    if cancelled:
        assert result.status == "CANCELLED" and await provider.transfer_count() == 0
    else:
        assert result.status in {"SUCCEEDED", "CANCELLED"}
    assert await provider.transfer_count() <= 1


async def test_aa_concurrent_payment_workflow_and_credit_once(pg_app):
    bank, provider, engine = await aa_runtime(pg_app)
    request = await published_request(pg_app, bank, engine)
    share_id = UUID(request["shares"][0]["share_id"])

    async def create():
        async with pg_app.state.test_session_factory() as session:
            return await AAService(session, pg_app.state.event_bus, engine, bank).payment(
                share_id, "mock-zhangsan", request["version"], "acc_salary"
            )

    first, second = await asyncio.wait_for(asyncio.gather(create(), create()), timeout=15)
    assert first.workflow_id == second.workflow_id
    before = await provider.effective_balance("dev-user-001", "acc_savings")
    operation = await pay(pg_app, bank, engine, request, "mock-zhangsan", str(share_id))
    assert operation.status.value == "SUCCEEDED"
    async with pg_app.state.test_session_factory() as session:
        stored = await session.get(OperationModel, operation.operation_id)
        key = stored.idempotency_key

    async def query():
        return await provider.get_transfer_status(
            user_id="mock-zhangsan",
            idempotency_key=key,
            provider_reference=operation.provider_reference,
        )

    await asyncio.gather(query(), query())
    assert await provider.effective_balance("dev-user-001", "acc_savings") == before + Decimal(
        "33.34"
    )
    assert await provider.transfer_count() == 1


@pytest.mark.parametrize("monthly", [False, True])
@pytest.mark.parametrize("case", ["security", "balance", "revoked", "scope", "unknown"])
async def test_schedule_due_controls_and_unknown_recovery(pg_app, schedule_enabled, case, monthly):
    from banking_api.application.operation_recovery_policy import OperationRecoveryPolicy
    from banking_api.persistence.models import ScheduledAuthorizationModel, SecurityGuardStateModel
    from banking_api.runtime.operation_recovery_worker import OperationRecoveryWorker
    from banking_api.transfers.provider import TransferProviderFaultMode, TransferProviderRequest

    if monthly:
        from test_recurring_transfers import recurring

        _, provider, _, engine = operation_runtime(pg_app)
        ready, _, occurrences = await recurring(pg_app, engine)
        async with pg_app.state.test_session_factory() as session:
            resource = await ScheduleService(session, engine).get(
                occurrences[1].schedule_id, ready.user_id
            )
    else:
        provider, engine, ready, resource = await scheduled(pg_app)
    now = resource.scheduled_for + timedelta(seconds=1)
    async with pg_app.state.test_session_factory() as session:
        row = await session.get(ScheduledTransferModel, resource.schedule_id)
        if case == "security":
            guard = await session.get(SecurityGuardStateModel, ready.user_id)
            if guard is None:
                guard = SecurityGuardStateModel(user_id=ready.user_id)
                session.add(guard)
            guard.locked_until, guard.lock_reason = now + timedelta(minutes=10), "CONTROL_BYPASS"
        elif case == "revoked":
            grant = await session.get(ScheduledAuthorizationModel, row.authorization_id)
            grant.revoked_at = now
        elif case == "scope":
            grant = await session.get(ScheduledAuthorizationModel, row.authorization_id)
            grant.payload_json = {**grant.payload_json, "amount": "999.00"}
        await session.commit()
    if case == "balance":
        from uuid import uuid4

        await provider.submit_transfer(
            TransferProviderRequest(
                user_id=ready.user_id,
                source_account_id="acc_salary",
                payee_id="payee_003",
                amount="23864.52",
                currency="CNY",
                idempotency_key=uuid4(),
            )
        )
    if case == "unknown":
        provider.fault_mode = TransferProviderFaultMode.TIMEOUT_AFTER_ACCEPT
    await ScheduleWorker(
        pg_app.state.test_session_factory, pg_app.state.event_bus, engine, clock=lambda: now
    ).run_once()
    async with pg_app.state.test_session_factory() as session:
        result = await ScheduleService(session, engine).get(resource.schedule_id, ready.user_id)
        if case == "unknown":
            assert result.status == "UNKNOWN" and result.operation_id
            original_id = result.operation_id
        else:
            assert result.status == "FAILED" and result.operation_id is None
    if case == "unknown":
        # Recovery after the execution window still queries the original Operation.
        recovery = OperationRecoveryWorker(
            pg_app.state.test_session_factory,
            pg_app.state.event_bus,
            engine,
            policy=OperationRecoveryPolicy.from_settings(),
            poll_interval_seconds=1,
            batch_size=10,
            clock=lambda: now + timedelta(hours=1),
        )
        await recovery.run_once()
        async with pg_app.state.test_session_factory() as session:
            result = await ScheduleService(session, engine).get(resource.schedule_id, ready.user_id)
            assert result.status == "SUCCEEDED" and result.operation_id == original_id
        assert await provider.transfer_count() == 1


async def test_aa_cancel_and_preparation_compete_without_double_credit(pg_app):
    from banking_test_helpers import authenticate_workflow

    from banking_api.application.operation_service import OperationService
    from banking_api.application.workflow_service import WorkflowService

    bank, provider, engine = await aa_runtime(pg_app)
    request = await published_request(pg_app, bank, engine)
    share_id = UUID(request["shares"][0]["share_id"])
    async with pg_app.state.test_session_factory() as session:
        workflow = await AAService(session, pg_app.state.event_bus, engine, bank).payment(
            share_id, "mock-zhangsan", request["version"], "acc_salary"
        )
        approved = await WorkflowService(session, pg_app.state.event_bus, engine).approve(
            workflow.workflow_id, user_id=workflow.user_id, expected_version=workflow.version
        )
    ready = await authenticate_workflow(pg_app, engine, approved)

    async def cancel():
        async with pg_app.state.test_session_factory() as session:
            try:
                return await AAService(session, pg_app.state.event_bus, engine, bank).close_share(
                    share_id, "dev-user-001", request["version"]
                )
            except Exception:
                return None

    async def commit():
        async with pg_app.state.test_session_factory() as session:
            try:
                return await OperationService(
                    session, pg_app.state.event_bus, engine
                ).commit_workflow(
                    ready.workflow_id, user_id=ready.user_id, expected_version=ready.version
                )
            except Exception:
                return None

    cancelled, operation = await asyncio.wait_for(asyncio.gather(cancel(), commit()), timeout=15)
    if cancelled:
        assert operation is None and await provider.transfer_count() == 0
        assert cancelled["shares"][0]["status"] == "CANCELLED"
    else:
        assert operation is not None and await provider.transfer_count() == 1


async def test_monthly_cancel_race_keeps_original_operations(pg_app, schedule_enabled):
    from test_recurring_transfers import recurring

    _, provider, _, engine = operation_runtime(pg_app)
    ready, root, rows = await recurring(pg_app, engine)
    now = rows[1].scheduled_for + timedelta(seconds=1)

    # First missed window must expire, and the second claimed occurrence competes with revocation.
    async def revoke():
        async with pg_app.state.test_session_factory() as session:
            return await ScheduleService(session, engine).cancel_series(
                root.schedule_id, ready.user_id, root.series_version
            )

    worker = ScheduleWorker(
        pg_app.state.test_session_factory, pg_app.state.event_bus, engine, clock=lambda: now
    )
    await asyncio.gather(revoke(), worker.run_once())
    async with pg_app.state.test_session_factory() as session:
        resources = [
            await ScheduleService(session, engine).get(r.schedule_id, ready.user_id) for r in rows
        ]
        assert resources[2].status == "CANCELLED" and resources[2].operation_id is None
        assert all(r.status in {"CANCELLED", "EXPIRED", "SUCCEEDED"} for r in resources)
        assert await session.scalar(select(func.count()).select_from(OperationModel)) <= 1
    count = await provider.transfer_count()
    assert count <= 1
    await worker.run_once()
    assert await provider.transfer_count() == count


async def test_pg_schedule_list_deletion_preserves_evidence(pg_app, schedule_enabled):
    from test_scheduled_transfers import test_delete_cancelled_schedule_preserves_evidence_and_owner

    await test_delete_cancelled_schedule_preserves_evidence_and_owner(pg_app, schedule_enabled)
