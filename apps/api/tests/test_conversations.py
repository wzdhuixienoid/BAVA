async def test_create_conversation_is_persisted(client) -> None:
    created = await client.post("/api/v1/conversations", json={"title": "Bootstrap test"})
    assert created.status_code == 201
    conversation_id = created.json()["conversation_id"]

    loaded = await client.get(f"/api/v1/conversations/{conversation_id}")
    assert loaded.status_code == 200
    assert loaded.json()["title"] == "Bootstrap test"
    assert loaded.json()["user_id"] == "dev-user-001"
    assert loaded.json()["messages"] == []


async def test_message_is_persisted_and_creates_task(client) -> None:
    created = await client.post("/api/v1/conversations", json={"title": "Messages"})
    conversation_id = created.json()["conversation_id"]

    accepted = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages", json={"content": "Hello"}
    )

    assert accepted.status_code == 202
    assert set(accepted.json()) == {"message_id", "task_id", "request_id"}
    loaded = await client.get(f"/api/v1/conversations/{conversation_id}")
    roles = [message["role"] for message in loaded.json()["messages"]]
    assert roles == ["USER", "ASSISTANT"]
    assert loaded.json()["messages"][1]["content"] == "启动运行时已收到你的消息。"
    tasks = await client.get(f"/api/v1/tasks?conversation_id={conversation_id}")
    assert len(tasks.json()) == 1
    assert tasks.json()[0]["task_type"] == "BOOTSTRAP_MESSAGE_PROCESSING"
