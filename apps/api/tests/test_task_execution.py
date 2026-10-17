import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from banking_api.application.conversation_service import ConversationService
from banking_api.application.task_execution_policy import TaskExecutionPolicy
from banking_api.config.settings import Settings
from banking_api.domain.enums import TaskStatus
from banking_api.llm.models import LLMResponse
from banking_api.llm.provider import LLMProviderError
from banking_api.persistence.models import MessageModel
from banking_api.persistence.repositories.tasks import TaskRepository
from banking_api.runtime.event_publisher import EventPublisher
from banking_api.runtime.task_execution_worker import (
    TaskExecutionWorker,
    TaskLeaseLostError,
)


def policy(*, lease: float = 0.12, heartbeat: float = 0.02) -> TaskExecutionPolicy:
    return TaskExecutionPolicy(
        lease_duration=timedelta(seconds=lease),
        heartbeat_interval=timedelta(seconds=heartbeat),
        initial_retry_delay=timedelta(seconds=1),
        maximum_retry_delay=timedelta(seconds=8),
        backoff_multiplier=2,
    )


async def create_task(app):  # type: ignore[no-untyped-def]
    factory = app.state.test_session_factory
    bus = app.state.event_bus
    async with factory() as session:
        conversation = await ConversationService(session, bus).create(
            user_id="task-worker-user", title="Durable Task"
        )
    async with factory() as session:
        accepted = await ConversationService(session, bus).accept_message(
            conversation_id=conversation.conversation_id,
            user_id="task-worker-user",
            content="查询余额",
        )
    return conversation, accepted


def test_task_policy_is_bounded_and_settings_validate_heartbeat() -> None:
    configured = policy()
    assert [configured.retry_delay(attempt).total_seconds() for attempt in range(1, 7)] == [
        1,
        2,
        4,
        8,
        8,
        8,
    ]
    with pytest.raises(ValueError, match="at least one"):
        configured.retry_delay(0)
    with pytest.raises(ValidationError, match="HEARTBEAT_SECONDS"):
        Settings(task_worker_lease_seconds=1, task_worker_heartbeat_seconds=1)


async def test_claims_only_due_runnable_tasks(app) -> None:
    factory = app.state.test_session_factory
    _, due = await create_task(app)
    _, future = await create_task(app)
    _, waiting = await create_task(app)
    _, terminal = await create_task(app)
    now = datetime.now(UTC)
    async with factory() as session:
        tasks = TaskRepository(session)
        future_model = await tasks.get(future.task_id)
        waiting_model = await tasks.get(waiting.task_id)
        terminal_model = await tasks.get(terminal.task_id)
        assert future_model and waiting_model and terminal_model
        future_model.next_run_at = now + timedelta(hours=1)
        await tasks.transition(waiting_model, TaskStatus.WAITING_USER)
        await tasks.transition(terminal_model, TaskStatus.COMPLETED)
        await session.commit()

    async with factory() as session:
        claims = await TaskRepository(session).claim_due(
            lease_owner="worker-a",
            now=now,
            lease_expires_at=now + timedelta(seconds=30),
            limit=10,
        )
        await session.commit()
    assert [claim.task_id for claim in claims] == [due.task_id]


class BlockingExecutor:
    def __init__(self, factory, *, clock=lambda: datetime.now(UTC)) -> None:  # type: ignore[no-untyped-def]
        self.factory = factory
        self.clock = clock
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.completed = False

    async def execute_claimed(self, claim, *, policy):  # type: ignore[no-untyped-def]
        self.started.set()
        await self.release.wait()
        async with self.factory() as session:
            tasks = TaskRepository(session)
            task = await tasks.get_owned(
                task_id=claim.task_id,
                lease_owner=claim.lease_owner,
                attempt=claim.attempt,
                now=self.clock(),
                for_update=True,
            )
            if task is None:
                raise TaskLeaseLostError
            await tasks.transition(task, TaskStatus.COMPLETED, output={"ok": True})
            await EventPublisher(session).persist(
                event_type="task.completed",
                conversation_id=claim.conversation_id,
                task_id=claim.task_id,
                data={"status": "COMPLETED", "version": task.version},
            )
            await session.commit()
        self.completed = True


async def test_heartbeat_renews_long_task_and_blocks_reclaim(app) -> None:
    factory = app.state.test_session_factory
    _, accepted = await create_task(app)
    clock = [datetime.now(UTC)]
    executor = BlockingExecutor(factory, clock=lambda: clock[0])
    configured = policy()
    worker = TaskExecutionWorker(
        factory,
        executor,
        policy=configured,
        poll_interval_seconds=0.01,
        batch_size=1,
        max_concurrency=1,
        worker_id="heartbeat-owner",
        clock=lambda: clock[0],
    )
    running = asyncio.create_task(worker.run_task_once(accepted.task_id))
    await asyncio.wait_for(executor.started.wait(), timeout=1)
    async with factory() as session:
        initial = await TaskRepository(session).get(accepted.task_id)
        assert initial and initial.lease_expires_at
        initial_expiry = initial.lease_expires_at

    # OS scheduling must not expire a 120 ms test lease while SQLite does I/O.
    # Advance logical time before renewal, then test beyond the original expiry.
    clock[0] = initial_expiry.replace(tzinfo=UTC) - timedelta(seconds=0.02)

    async def wait_for_renewal():
        while True:
            async with factory() as session:
                renewed = await TaskRepository(session).get(accepted.task_id)
                if renewed and renewed.lease_expires_at > initial_expiry:
                    return renewed
            await asyncio.sleep(0.01)

    renewed = await asyncio.wait_for(wait_for_renewal(), timeout=5)
    clock[0] = initial_expiry.replace(tzinfo=UTC) + timedelta(seconds=0.01)
    assert renewed.lease_expires_at.replace(tzinfo=UTC) > clock[0]
    async with factory() as session:
        claims = await TaskRepository(session).claim_due(
            lease_owner="other-worker",
            now=clock[0],
            lease_expires_at=clock[0] + timedelta(seconds=1),
            limit=1,
        )
        await session.rollback()
    assert claims == []
    executor.release.set()
    assert await asyncio.wait_for(running, timeout=1) is True
    assert executor.completed is True


async def test_heartbeat_lease_loss_cancels_and_fences_completion(app) -> None:
    factory = app.state.test_session_factory
    _, accepted = await create_task(app)
    executor = BlockingExecutor(factory)
    worker = TaskExecutionWorker(
        factory,
        executor,
        policy=policy(),
        poll_interval_seconds=0.01,
        batch_size=1,
        max_concurrency=1,
        worker_id="stale-worker",
    )
    running = asyncio.create_task(worker.run_task_once(accepted.task_id))
    await asyncio.wait_for(executor.started.wait(), timeout=1)
    async with factory() as session:
        task = await TaskRepository(session).get(accepted.task_id)
        assert task is not None
        task.lease_owner = "new-owner"
        task.execution_attempts += 1
        task.lease_expires_at = datetime.now(UTC) + timedelta(seconds=1)
        await session.commit()

    assert await asyncio.wait_for(running, timeout=1) is True
    async with factory() as session:
        task = await TaskRepository(session).get(accepted.task_id)
    assert task is not None
    assert task.status is TaskStatus.RUNNING
    assert task.lease_owner == "new-owner"
    assert task.output_json is None
    assert executor.completed is False


async def test_task_worker_lifecycle_starts_and_stops(app) -> None:
    worker = TaskExecutionWorker(
        app.state.test_session_factory,
        BlockingExecutor(app.state.test_session_factory),
        policy=policy(),
        poll_interval_seconds=0.01,
        batch_size=1,
        max_concurrency=1,
    )
    worker.start()
    assert worker.is_running
    await worker.stop()
    assert not worker.is_running


async def test_read_task_retry_converges_without_duplicate_assistant_output(app) -> None:
    factory = app.state.test_session_factory
    conversation, accepted = await create_task(app)
    first = app.state.test_make_runner([LLMProviderError("temporary outage")])
    await first.run(accepted.task_id)

    async with factory() as session:
        task = await TaskRepository(session).get(accepted.task_id)
        assert task is not None and task.status is TaskStatus.INTERRUPTED
        assert task.error_json["retryable"] is True
        task.next_run_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    second = app.state.test_make_runner([LLMResponse(content="余额查询已恢复。")])
    await second.run(accepted.task_id)
    # Terminal rows remain excluded from future claims.
    await second.run(accepted.task_id)

    async with factory() as session:
        task = await TaskRepository(session).get(accepted.task_id)
        assistant_messages = list(
            (
                await session.execute(
                    select(MessageModel).where(
                        MessageModel.conversation_id == conversation.conversation_id,
                        MessageModel.role == "ASSISTANT",
                    )
                )
            ).scalars()
        )
    assert task is not None and task.status is TaskStatus.COMPLETED
    assert task.execution_attempts == 2
    assert [message.content for message in assistant_messages] == ["余额查询已恢复。"]
