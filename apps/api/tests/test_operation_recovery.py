import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from test_transfer_operations import (
    authorize_workflow,
    operation_runtime,
)

from banking_api.application.operation_recovery_policy import OperationRecoveryPolicy
from banking_api.application.operation_service import OperationService
from banking_api.domain.enums import OperationStatus
from banking_api.persistence.models import OperationModel
from banking_api.persistence.repositories.operations import OperationRepository
from banking_api.runtime.operation_recovery_worker import OperationRecoveryWorker
from banking_api.transfers.provider import TransferProviderFaultMode, TransferProviderRequest


def recovery_policy() -> OperationRecoveryPolicy:
    return OperationRecoveryPolicy(
        lease_duration=timedelta(seconds=2),
        initial_retry_delay=timedelta(milliseconds=10),
        maximum_retry_delay=timedelta(milliseconds=40),
        backoff_multiplier=2,
    )


def test_recovery_backoff_is_deterministic_and_bounded() -> None:
    policy = recovery_policy()
    assert policy.retry_delay(1) == timedelta(milliseconds=10)
    assert policy.retry_delay(2) == timedelta(milliseconds=20)
    assert policy.retry_delay(3) == timedelta(milliseconds=40)
    assert policy.retry_delay(10) == timedelta(milliseconds=40)


async def test_claim_eligibility_due_active_expired_and_terminal(app) -> None:
    _, _, _, engine = operation_runtime(app)
    ready = await authorize_workflow(app, engine, user_id="claim-user")
    async with app.state.test_session_factory() as session:
        created = await OperationService(session, app.state.event_bus, engine).prepare_transfer(
            ready.workflow_id,
            user_id=ready.user_id,
            expected_version=ready.version,
        )

    now = datetime.now(UTC)
    async with app.state.test_session_factory() as session:
        operation = await session.get(OperationModel, created.operation_id)
        operation.next_reconcile_at = now + timedelta(minutes=1)  # type: ignore[union-attr]
        await session.commit()
    async with app.state.test_session_factory() as session:
        claims = await OperationRepository(session).claim_due(
            lease_owner="worker-a",
            now=now,
            lease_expires_at=now + timedelta(seconds=2),
            limit=10,
        )
        await session.commit()
    assert claims == []

    async with app.state.test_session_factory() as session:
        operation = await session.get(OperationModel, created.operation_id)
        operation.next_reconcile_at = now  # type: ignore[union-attr]
        operation.lease_owner = "worker-a"  # type: ignore[union-attr]
        operation.lease_expires_at = now + timedelta(seconds=1)  # type: ignore[union-attr]
        await session.commit()
    async with app.state.test_session_factory() as session:
        assert not await OperationRepository(session).claim_due(
            lease_owner="worker-b",
            now=now,
            lease_expires_at=now + timedelta(seconds=2),
            limit=10,
        )
        await session.rollback()

    later = now + timedelta(seconds=2)
    async with app.state.test_session_factory() as session:
        claims = await OperationRepository(session).claim_due(
            lease_owner="worker-b",
            now=later,
            lease_expires_at=later + timedelta(seconds=2),
            limit=10,
        )
        await session.commit()
    assert [claim.operation_id for claim in claims] == [created.operation_id]
    assert claims[0].reclaimed is True

    async with app.state.test_session_factory() as session:
        operation = await session.get(OperationModel, created.operation_id)
        operation.status = OperationStatus.SUCCEEDED  # type: ignore[union-attr]
        operation.lease_owner = None  # type: ignore[union-attr]
        operation.lease_expires_at = None  # type: ignore[union-attr]
        await session.commit()
    async with app.state.test_session_factory() as session:
        assert not await OperationRepository(session).claim_due(
            lease_owner="worker-c",
            now=later,
            lease_expires_at=later + timedelta(seconds=2),
            limit=10,
        )


async def test_worker_recovers_created_after_provider_accept_with_exactly_one_debit(app) -> None:
    _, provider, _, engine = operation_runtime(app)
    ready = await authorize_workflow(app, engine, user_id="worker-crash-user")
    async with app.state.test_session_factory() as session:
        created = await OperationService(session, app.state.event_bus, engine).prepare_transfer(
            ready.workflow_id,
            user_id=ready.user_id,
            expected_version=ready.version,
        )
    async with app.state.test_session_factory() as session:
        operation = await session.get(OperationModel, created.operation_id)
        stable_key = operation.idempotency_key  # type: ignore[union-attr]
        payload = operation.payload_json  # type: ignore[union-attr]
    await provider.submit_transfer(
        TransferProviderRequest(
            idempotency_key=stable_key,
            source_account_id=payload["source_account_id"],
            payee_id=payload["payee_id"],
            amount=payload["amount"],
            currency=payload["currency"],
        )
    )

    worker = OperationRecoveryWorker(
        app.state.test_session_factory,
        app.state.event_bus,
        engine,
        policy=recovery_policy(),
        poll_interval_seconds=0.01,
        batch_size=10,
        worker_id="worker-restart",
    )
    assert await worker.run_once() == 1
    assert await provider.transfer_count() == 1
    async with app.state.test_session_factory() as session:
        recovered = await session.get(OperationModel, created.operation_id)
    assert recovered.status is OperationStatus.SUCCEEDED  # type: ignore[union-attr]
    assert recovered.idempotency_key == stable_key  # type: ignore[union-attr]
    assert recovered.reconcile_attempts == 1  # type: ignore[union-attr]
    assert recovered.last_reconcile_at is not None  # type: ignore[union-attr]
    assert recovered.next_reconcile_at is None  # type: ignore[union-attr]
    assert recovered.lease_owner is None  # type: ignore[union-attr]
    assert recovered.lease_expires_at is None  # type: ignore[union-attr]


async def test_unknown_background_recovery_is_query_only(app) -> None:
    _, provider, _, engine = operation_runtime(
        app, fault_mode=TransferProviderFaultMode.TIMEOUT_AFTER_ACCEPT
    )
    ready = await authorize_workflow(app, engine, user_id="unknown-worker-user")
    async with app.state.test_session_factory() as session:
        unknown = await OperationService(
            session,
            app.state.event_bus,
            engine,
            recovery_policy=recovery_policy(),
        ).commit_workflow(
            ready.workflow_id,
            user_id=ready.user_id,
            expected_version=ready.version,
        )
    assert unknown.status is OperationStatus.UNKNOWN
    assert await provider.transfer_count() == 1

    async with app.state.test_session_factory() as session:
        operation = await session.get(OperationModel, unknown.operation_id)
        operation.next_reconcile_at = datetime.now(UTC) - timedelta(seconds=1)  # type: ignore[union-attr]
        await session.commit()

    async def forbidden_submit(_request):  # type: ignore[no-untyped-def]
        raise AssertionError("UNKNOWN recovery must never submit")

    provider.submit_transfer = forbidden_submit  # type: ignore[method-assign]
    worker = OperationRecoveryWorker(
        app.state.test_session_factory,
        app.state.event_bus,
        engine,
        policy=recovery_policy(),
        poll_interval_seconds=0.01,
        batch_size=1,
        worker_id="worker-query-only",
    )
    assert await worker.run_once() == 1
    assert await provider.transfer_count() == 1
    async with app.state.test_session_factory() as session:
        recovered = await session.scalar(
            select(OperationModel).where(
                OperationModel.operation_id == unknown.operation_id
            )
        )
    assert recovered.status is OperationStatus.SUCCEEDED  # type: ignore[union-attr]
    assert recovered.reconcile_attempts == 2  # type: ignore[union-attr]


async def test_provider_query_unavailable_stays_unknown_and_reschedules(app) -> None:
    _, provider, _, engine = operation_runtime(app)
    ready = await authorize_workflow(app, engine, user_id="unavailable-user")
    async with app.state.test_session_factory() as session:
        created = await OperationService(session, app.state.event_bus, engine).prepare_transfer(
            ready.workflow_id,
            user_id=ready.user_id,
            expected_version=ready.version,
        )
    async with app.state.test_session_factory() as session:
        operation = await session.get(OperationModel, created.operation_id)
        operation.status = OperationStatus.UNKNOWN  # type: ignore[union-attr]
        await session.commit()

    async def unavailable(**_kwargs):  # type: ignore[no-untyped-def]
        raise TimeoutError("provider unavailable")

    provider.get_transfer_status = unavailable  # type: ignore[method-assign]
    worker = OperationRecoveryWorker(
        app.state.test_session_factory,
        app.state.event_bus,
        engine,
        policy=recovery_policy(),
        poll_interval_seconds=0.01,
        batch_size=1,
        worker_id="worker-unavailable",
    )
    assert await worker.run_once() == 1
    async with app.state.test_session_factory() as session:
        recovered = await session.get(OperationModel, created.operation_id)
    assert recovered.status is OperationStatus.UNKNOWN  # type: ignore[union-attr]
    assert recovered.reconcile_attempts == 1  # type: ignore[union-attr]
    assert recovered.last_reconcile_at is not None  # type: ignore[union-attr]
    assert recovered.next_reconcile_at > recovered.last_reconcile_at  # type: ignore[union-attr,operator]
    assert recovered.lease_owner is None  # type: ignore[union-attr]


async def test_submitted_background_recovery_queries_without_resubmission(app) -> None:
    _, provider, _, engine = operation_runtime(app)
    ready = await authorize_workflow(app, engine, user_id="submitted-worker-user")
    async with app.state.test_session_factory() as session:
        created = await OperationService(session, app.state.event_bus, engine).prepare_transfer(
            ready.workflow_id,
            user_id=ready.user_id,
            expected_version=ready.version,
        )
    async with app.state.test_session_factory() as session:
        operation = await session.get(OperationModel, created.operation_id)
        payload = operation.payload_json  # type: ignore[union-attr]
        key = operation.idempotency_key  # type: ignore[union-attr]
    accepted = await provider.submit_transfer(
        TransferProviderRequest(
            idempotency_key=key,
            source_account_id=payload["source_account_id"],
            payee_id=payload["payee_id"],
            amount=payload["amount"],
            currency=payload["currency"],
        )
    )
    async with app.state.test_session_factory() as session:
        operation = await session.get(OperationModel, created.operation_id)
        operation.status = OperationStatus.SUBMITTED  # type: ignore[union-attr]
        operation.provider_reference = accepted.provider_reference  # type: ignore[union-attr]
        await session.commit()

    async def forbidden_submit(_request):  # type: ignore[no-untyped-def]
        raise AssertionError("SUBMITTED recovery must not submit")

    provider.submit_transfer = forbidden_submit  # type: ignore[method-assign]
    worker = OperationRecoveryWorker(
        app.state.test_session_factory,
        app.state.event_bus,
        engine,
        policy=recovery_policy(),
        poll_interval_seconds=0.01,
        batch_size=1,
        worker_id="worker-submitted",
    )
    assert await worker.run_once() == 1
    assert await provider.transfer_count() == 1
    async with app.state.test_session_factory() as session:
        recovered = await session.get(OperationModel, created.operation_id)
    assert recovered.status is OperationStatus.SUCCEEDED  # type: ignore[union-attr]


async def test_worker_loop_starts_and_stops_cleanly(app) -> None:
    _, _, _, engine = operation_runtime(app)
    worker = OperationRecoveryWorker(
        app.state.test_session_factory,
        app.state.event_bus,
        engine,
        policy=recovery_policy(),
        poll_interval_seconds=0.01,
        batch_size=1,
        worker_id="worker-lifecycle",
    )
    worker.start()
    assert worker.is_running is True
    await asyncio.sleep(0.02)
    await worker.stop()
    assert worker.is_running is False
