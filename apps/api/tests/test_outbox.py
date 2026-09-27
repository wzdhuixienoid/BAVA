import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from banking_api.application.conversation_service import ConversationService
from banking_api.application.outbox_publication_policy import OutboxPublicationPolicy
from banking_api.persistence.models import (
    ConversationModel,
    EventModel,
    MessageModel,
    OutboxEventModel,
    TaskModel,
)
from banking_api.persistence.repositories.outbox import OutboxRepository
from banking_api.runtime.event_bus import EventBus
from banking_api.runtime.event_publisher import EventPublisher
from banking_api.runtime.outbox_publisher import OutboxPublisher


def policy(*, lease_seconds: float = 2) -> OutboxPublicationPolicy:
    return OutboxPublicationPolicy(
        lease_duration=timedelta(seconds=lease_seconds),
        initial_retry_delay=timedelta(seconds=1),
        maximum_retry_delay=timedelta(seconds=8),
        backoff_multiplier=2,
    )


def test_outbox_retry_policy_is_deterministic_and_capped() -> None:
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


class RecordingEventBus(EventBus):
    def __init__(self, *, failures: int = 0) -> None:
        super().__init__()
        self.failures = failures
        self.published = []

    async def publish(self, event):  # type: ignore[no-untyped-def]
        if self.failures:
            self.failures -= 1
            raise RuntimeError("temporary event bus failure")
        self.published.append(event)
        await super().publish(event)


async def create_message_events(factory, bus):  # type: ignore[no-untyped-def]
    async with factory() as session:
        conversation = await ConversationService(session, bus).create(
            user_id="outbox-user", title="Outbox"
        )
    async with factory() as session:
        accepted = await ConversationService(session, bus).accept_message(
            conversation_id=conversation.conversation_id,
            user_id="outbox-user",
            content="durable notification",
        )
    return conversation, accepted


async def test_event_and_outbox_are_created_atomically(app) -> None:
    factory = app.state.test_session_factory
    _, accepted = await create_message_events(factory, app.state.event_bus)
    async with factory() as session:
        events = list(
            (
                await session.execute(
                    select(EventModel)
                    .where(EventModel.task_id == accepted.task_id)
                    .order_by(EventModel.sequence)
                )
            ).scalars()
        )
        outbox = list(
            (
                await session.execute(
                    select(OutboxEventModel).order_by(OutboxEventModel.created_at)
                )
            ).scalars()
        )
    assert [event.event_type for event in events] == [
        "conversation.message.created",
        "task.created",
    ]
    assert {row.event_id for row in outbox} == {event.event_id for event in events}
    assert all(row.published_at is None for row in outbox)


async def test_outbox_insert_failure_rolls_back_business_event_and_state(
    app, monkeypatch
) -> None:
    factory = app.state.test_session_factory
    bus = app.state.event_bus
    async with factory() as session:
        conversation = await ConversationService(session, bus).create(
            user_id="rollback-user", title="Rollback"
        )

    async def fail_enqueue(self, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("forced outbox failure")

    monkeypatch.setattr(OutboxRepository, "enqueue", fail_enqueue)
    async with factory() as session:
        with pytest.raises(RuntimeError, match="forced outbox failure"):
            await ConversationService(session, bus).accept_message(
                conversation_id=conversation.conversation_id,
                user_id="rollback-user",
                content="must roll back",
            )
        await session.rollback()

    async with factory() as session:
        message_count = await session.scalar(
            select(func.count())
            .select_from(MessageModel)
            .where(MessageModel.conversation_id == conversation.conversation_id)
        )
        task_count = await session.scalar(
            select(func.count())
            .select_from(TaskModel)
            .where(TaskModel.conversation_id == conversation.conversation_id)
        )
        event_count = await session.scalar(
            select(func.count())
            .select_from(EventModel)
            .where(EventModel.conversation_id == conversation.conversation_id)
        )
        outbox_count = await session.scalar(
            select(func.count()).select_from(OutboxEventModel)
        )
    assert (message_count, task_count, event_count, outbox_count) == (0, 0, 0, 0)


async def test_committed_event_waits_for_outbox_and_has_no_direct_double_path(app) -> None:
    factory = app.state.test_session_factory
    bus = app.state.event_bus
    async with factory() as session:
        conversation = await ConversationService(session, bus).create(
            user_id="live-user", title="Live"
        )

    async with bus.subscribe(conversation.conversation_id) as queue:
        async with factory() as session:
            await ConversationService(session, bus).accept_message(
                conversation_id=conversation.conversation_id,
                user_id="live-user",
                content="publish later",
            )
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(queue.get(), timeout=0.02)
        publisher = OutboxPublisher(
            factory,
            bus,
            policy=policy(),
            poll_interval_seconds=0.01,
            batch_size=10,
            publisher_id="unit-publisher",
        )
        assert await publisher.run_once() == 2
        first = await asyncio.wait_for(queue.get(), timeout=1)
        second = await asyncio.wait_for(queue.get(), timeout=1)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(queue.get(), timeout=0.02)
    assert [first.event_type, second.event_type] == [
        "conversation.message.created",
        "task.created",
    ]


async def test_temporary_failure_retries_without_changing_business_state(app) -> None:
    factory = app.state.test_session_factory
    bus = RecordingEventBus(failures=1)
    async with factory() as session:
        conversation = await ConversationService(session, bus).create(
            user_id="retry-user", title="Retry"
        )
        await EventPublisher(session).persist(
            event_type="test.retry",
            conversation_id=conversation.conversation_id,
            task_id=None,
            data={"business_version": 1},
        )
        await session.commit()
    clock = [datetime.now(UTC)]
    publisher = OutboxPublisher(
        factory,
        bus,
        policy=policy(),
        poll_interval_seconds=0.01,
        batch_size=1,
        publisher_id="retry-publisher",
        clock=lambda: clock[0],
    )
    assert await publisher.run_once() == 1
    async with factory() as session:
        row = (
            await session.execute(
                select(OutboxEventModel).order_by(OutboxEventModel.created_at)
            )
        ).scalars().first()
        conversation_count = await session.scalar(
            select(func.count())
            .select_from(ConversationModel)
            .where(ConversationModel.conversation_id == conversation.conversation_id)
        )
    assert row is not None
    assert row.published_at is None
    assert row.publish_attempts == 1
    assert row.last_error_code == "EVENT_BUS_PUBLISH_FAILED"
    assert row.next_publish_at.replace(tzinfo=UTC) == clock[0] + timedelta(seconds=1)
    assert conversation_count == 1
    assert await publisher.run_once() == 0

    clock[0] += timedelta(seconds=1)
    assert await publisher.run_once() == 1
    async with factory() as session:
        published = await session.get(OutboxEventModel, row.outbox_id)
    assert published is not None
    assert published.published_at.replace(tzinfo=UTC) == clock[0]
    assert published.publish_attempts == 2
    assert published.next_publish_at is None
    assert published.last_error_code is None


async def test_publish_before_ack_crash_is_at_least_once(app, monkeypatch) -> None:
    factory = app.state.test_session_factory
    bus = RecordingEventBus()
    async with factory() as session:
        conversation = await ConversationService(session, bus).create(
            user_id="duplicate-user", title="At least once"
        )
        event = await EventPublisher(session).persist(
            event_type="test.durable",
            conversation_id=conversation.conversation_id,
            task_id=None,
            data={"business_version": 1},
        )
        await session.commit()

    clock = [datetime.now(UTC)]
    crashed = OutboxPublisher(
        factory,
        bus,
        policy=policy(lease_seconds=1),
        poll_interval_seconds=0.01,
        batch_size=1,
        publisher_id="publisher-a",
        clock=lambda: clock[0],
    )

    async def crash_before_ack(_claim):  # type: ignore[no-untyped-def]
        raise RuntimeError("process died before mark-published")

    monkeypatch.setattr(crashed, "_mark_published", crash_before_ack)
    with pytest.raises(RuntimeError, match="process died"):
        await crashed.run_once()
    assert [item.event_id for item in bus.published] == [event.event_id]

    clock[0] += timedelta(seconds=2)
    restarted = OutboxPublisher(
        factory,
        bus,
        policy=policy(lease_seconds=1),
        poll_interval_seconds=0.01,
        batch_size=1,
        publisher_id="publisher-b",
        clock=lambda: clock[0],
    )
    assert await restarted.run_once() == 1
    assert [item.event_id for item in bus.published] == [event.event_id, event.event_id]
    assert await restarted.run_once() == 0

    async with factory() as session:
        event_count = await session.scalar(
            select(func.count())
            .select_from(EventModel)
            .where(EventModel.event_id == event.event_id)
        )
        rows = list(
            (
                await session.execute(
                    select(OutboxEventModel).where(
                        OutboxEventModel.event_id == event.event_id
                    )
                )
            ).scalars()
        )
        conversation_count = await session.scalar(
            select(func.count())
            .select_from(ConversationModel)
            .where(ConversationModel.conversation_id == conversation.conversation_id)
        )
    assert event_count == 1
    assert len(rows) == 1
    assert rows[0].publish_attempts == 2
    assert rows[0].published_at is not None
    assert conversation_count == 1
