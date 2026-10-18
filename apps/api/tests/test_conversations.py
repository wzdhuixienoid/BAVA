from uuid import UUID

import pytest

from banking_api.domain.enums import MessageRole
from banking_api.persistence.repositories.conversations import ConversationRepository
from banking_api.persistence.repositories.messages import MessageRepository


async def test_first_reply_names_conversation_and_later_replies_keep_title(app, client) -> None:
    created = await client.post("/api/v1/conversations", json={"title": "新对话"})
    cid = created.json()["conversation_id"]
    accepted = await client.post(
        f"/api/v1/conversations/{cid}/messages", json={"content": "请帮我分析8月份消费"}
    )
    assert (await client.get(f"/api/v1/conversations/{cid}")).json()["title"] == "新对话"
    await app.state.task_runner.run(UUID(accepted.json()["task_id"]))
    assert (await client.get(f"/api/v1/conversations/{cid}")).json()["title"] == "分析8月份消费"
    async with app.state.test_session_factory() as session:
        messages = MessageRepository(session)
        await messages.create(
            conversation_id=UUID(cid), role=MessageRole.USER, content="现在改查账户"
        )
        await messages.create(
            conversation_id=UUID(cid), role=MessageRole.ASSISTANT, content="已查询账户"
        )
        await session.commit()
    assert (await client.get(f"/api/v1/conversations/{cid}")).json()["title"] == "分析8月份消费"


async def test_manual_default_title_is_preserved_after_first_reply(app, client) -> None:
    created = await client.post("/api/v1/conversations", json={"title": "新对话"})
    cid = created.json()["conversation_id"]
    renamed = await client.patch(f"/api/v1/conversations/{cid}", json={"title": " 新对话 "})
    assert renamed.status_code == 200 and renamed.json()["title"] == "新对话"
    accepted = await client.post(
        f"/api/v1/conversations/{cid}/messages", json={"content": "我有哪些账户"}
    )
    await app.state.task_runner.run(UUID(accepted.json()["task_id"]))
    assert (await client.get(f"/api/v1/conversations/{cid}")).json()["title"] == "新对话"
    async with app.state.test_session_factory() as session:
        model = await ConversationRepository(session).get(UUID(cid))
        assert model.title_is_custom is True


async def test_rename_rejects_foreign_and_deleted_conversations(app, client) -> None:
    async with app.state.test_session_factory() as session:
        foreign = await ConversationRepository(session).create(user_id="another-user", title="私有")
        await session.commit()
    assert (
        await client.patch(
            f"/api/v1/conversations/{foreign.conversation_id}", json={"title": "改名"}
        )
    ).status_code == 404
    created = await client.post("/api/v1/conversations", json={"title": "新对话"})
    cid = created.json()["conversation_id"]
    assert (await client.delete(f"/api/v1/conversations/{cid}")).status_code == 204
    assert (
        await client.patch(f"/api/v1/conversations/{cid}", json={"title": "改名"})
    ).status_code == 404


@pytest.mark.parametrize("title", ["", "  ", "x" * 101, "名称\n换行"])
async def test_rename_validates_title(client, title) -> None:
    created = await client.post("/api/v1/conversations", json={"title": "新对话"})
    cid = created.json()["conversation_id"]
    assert (
        await client.patch(f"/api/v1/conversations/{cid}", json={"title": title})
    ).status_code == 422


async def test_create_conversation_is_persisted(client) -> None:
    created = await client.post("/api/v1/conversations", json={"title": "Bootstrap test"})
    assert created.status_code == 201
    conversation_id = created.json()["conversation_id"]

    loaded = await client.get(f"/api/v1/conversations/{conversation_id}")
    assert loaded.status_code == 200
    assert loaded.json()["title"] == "Bootstrap test"
    assert loaded.json()["user_id"] == "dev-user-001"
    assert loaded.json()["messages"] == []


async def test_message_is_persisted_and_creates_task(app, client) -> None:
    created = await client.post("/api/v1/conversations", json={"title": "Messages"})
    conversation_id = created.json()["conversation_id"]

    accepted = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages", json={"content": "Hello"}
    )

    assert accepted.status_code == 202
    assert set(accepted.json()) == {"message_id", "task_id", "request_id"}
    await app.state.task_runner.run(UUID(accepted.json()["task_id"]))
    loaded = await client.get(f"/api/v1/conversations/{conversation_id}")
    roles = [message["role"] for message in loaded.json()["messages"]]
    assert roles == ["USER", "ASSISTANT"]
    assert "尚未取得本次查询" in loaded.json()["messages"][1]["content"]
    tasks = await client.get(f"/api/v1/tasks?conversation_id={conversation_id}")
    assert len(tasks.json()) == 1
    assert tasks.json()[0]["task_type"] == "BANKING_REQUEST"
    assert tasks.json()[0]["executor_type"] == "AGENT"
    assert tasks.json()[0]["executor_id"] == "agent:personal-banking"
