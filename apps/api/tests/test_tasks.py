from uuid import UUID

from banking_api.application.conversation_service import ConversationService
from banking_api.application.task_service import TaskService
from banking_api.domain.enums import TaskStatus


async def test_runtime_transitions_task_to_completed(client) -> None:
    created = await client.post("/api/v1/conversations", json={"title": "Tasks"})
    conversation_id = created.json()["conversation_id"]
    accepted = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages", json={"content": "Hello"}
    )
    task_id = accepted.json()["task_id"]

    task = await client.get(f"/api/v1/tasks/{task_id}")
    assert task.status_code == 200
    assert task.json()["status"] == "COMPLETED"
    assert task.json()["version"] == 3


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

    await app.state.bootstrap_runtime.run(accepted.task_id, fail=True)

    async with factory() as session:
        task = await TaskService(session).get(
            UUID(str(accepted.task_id)), user_id="dev-user-001"
        )
        assert task.status is TaskStatus.FAILED
        assert task.version == 3
        assert task.error == {
            "type": "RuntimeError",
            "message": "Controlled bootstrap processing failure",
        }
