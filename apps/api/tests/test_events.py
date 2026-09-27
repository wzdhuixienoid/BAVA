from datetime import timedelta
from uuid import UUID

from sqlalchemy import select

from banking_api.application.outbox_publication_policy import OutboxPublicationPolicy
from banking_api.persistence.models import EventModel
from banking_api.runtime.outbox_publisher import OutboxPublisher


async def test_task_events_are_durable_and_sequenced(client, app) -> None:
    created = await client.post("/api/v1/conversations", json={"title": "Events"})
    conversation_id = created.json()["conversation_id"]
    accepted = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages", json={"content": "Hello"}
    )
    task_id = UUID(accepted.json()["task_id"])

    factory = app.state.test_session_factory
    async with factory() as session:
        result = await session.execute(
            select(EventModel).where(EventModel.task_id == task_id).order_by(EventModel.sequence)
        )
        events = list(result.scalars())

    assert [event.event_type for event in events] == [
        "conversation.message.created",
        "task.created",
        "task.started",
        "task.progress",
        "request.routed",
        "agent.run.started",
        "llm.request.started",
        "llm.request.completed",
        "agent.run.completed",
        "task.completed",
        "conversation.message.completed",
    ]
    assert [event.sequence for event in events] == sorted(event.sequence for event in events)
    assert len({event.sequence for event in events}) == len(events)


async def test_live_event_bus_delivers_persisted_event(app, client) -> None:
    factory = app.state.test_session_factory
    bus = app.state.event_bus
    async with factory() as session:
        from banking_api.application.conversation_service import ConversationService

        conversation = await ConversationService(session, bus).create(
            user_id="dev-user-001", title="Live"
        )

    async with bus.subscribe(conversation.conversation_id) as queue:
        async with factory() as session:
            await ConversationService(session, bus).accept_message(
                conversation_id=conversation.conversation_id,
                user_id="dev-user-001",
                content="Observe",
            )
        publisher = OutboxPublisher(
            factory,
            bus,
            policy=OutboxPublicationPolicy(
                lease_duration=timedelta(seconds=30),
                initial_retry_delay=timedelta(seconds=1),
                maximum_retry_delay=timedelta(seconds=8),
                backoff_multiplier=2,
            ),
            poll_interval_seconds=0.01,
            batch_size=10,
            publisher_id="event-test-publisher",
        )
        assert await publisher.run_once() == 2
        first = await queue.get()
        second = await queue.get()

    assert [first.event_type, second.event_type] == [
        "conversation.message.created",
        "task.created",
    ]
    async with factory() as session:
        durable = list(
            (
                await session.execute(
                    select(EventModel)
                    .where(EventModel.task_id == first.task_id)
                    .order_by(EventModel.sequence)
                )
            ).scalars()
        )
    assert [first.event_id, second.event_id] == [event.event_id for event in durable]
    resource_events = (await client.get(f"/api/v1/tasks/{first.task_id}/events")).json()
    assert [first.event_id, second.event_id] == [
        UUID(item["event_id"]) for item in resource_events
    ]
