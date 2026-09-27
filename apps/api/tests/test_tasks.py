from uuid import UUID

from banking_api.application.conversation_service import ConversationService
from banking_api.application.task_service import TaskService
from banking_api.domain.enums import TaskStatus
from banking_api.llm.provider import LLMProviderError


async def test_runtime_transitions_task_to_completed(app, client) -> None:
    created = await client.post("/api/v1/conversations", json={"title": "Tasks"})
    conversation_id = created.json()["conversation_id"]
    accepted = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages", json={"content": "Hello"}
    )
    task_id = accepted.json()["task_id"]

    pending = await client.get(f"/api/v1/tasks/{task_id}")
    assert pending.json()["status"] == "PENDING"
    await app.state.task_runner.run(UUID(task_id))
    task = await client.get(f"/api/v1/tasks/{task_id}")
    assert task.status_code == 200
    assert task.json()["status"] == "COMPLETED"
    assert task.json()["version"] == 4
    assert task.json()["executor_type"] == "AGENT"
    assert task.json()["executor_id"] == "agent:minimal-banking"


async def test_controlled_failure_sets_failed_and_persists_event(app) -> None:
    factory = app.state.test_session_factory
    bus = app.state.event_bus
    async with factory() as session:
        service = ConversationService(session, bus)
        conversation = await service.create(user_id="dev-user-001", title="Failure")
    async with factory() as session:
        accepted = await ConversationService(session, bus).accept_message(
            conversation_id=conversation.conversation_id,
            user_id="dev-user-001",
            content="Fail safely",
        )

    runner = app.state.test_make_runner([LLMProviderError("provider unavailable")])
    await runner.run(accepted.task_id)

    async with factory() as session:
        task = await TaskService(session).get(
            UUID(str(accepted.task_id)), user_id="dev-user-001"
        )
        assert task.status is TaskStatus.INTERRUPTED
        assert task.version == 4
        assert task.error == {
            "category": "EXTERNAL",
            "code": "LLM_PROVIDER_ERROR",
            "message": "LLM provider request failed",
            "retryable": True,
        }


async def test_task_developer_trace_is_authorized_and_sanitized(app, client) -> None:
    created = await client.post("/api/v1/conversations", json={"title": "Trace"})
    conversation_id = created.json()["conversation_id"]
    accepted = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages", json={"content": "Hello"}
    )

    await app.state.task_runner.run(UUID(accepted.json()["task_id"]))
    response = await client.get(f"/api/v1/tasks/{accepted.json()['task_id']}/events")

    assert response.status_code == 200
    event_types = [event["event_type"] for event in response.json()]
    assert "llm.request.started" in event_types
    assert "agent.run.completed" in event_types
    serialized = str([event["data"] for event in response.json()]).lower()
    assert "prompt_dump" not in serialized
    assert "api_key" not in serialized
