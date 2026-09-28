from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from banking_api.domain.enums import RuntimeBackend, TaskStatus
from banking_api.llm.openai_compatible_provider import OpenAICompatibleProvider
from banking_api.persistence.database import Base
from banking_api.persistence.repositories.conversations import ConversationRepository
from banking_api.persistence.repositories.events import EventRepository
from banking_api.persistence.repositories.tasks import TaskRepository
from banking_api.runtime.event_bus import EventBus
from banking_api.runtime.runtime_factory import AgentRuntimeFactory
from banking_api.runtime.task_reconciliation import TaskReconciliationService
from banking_api.tools.models import (
    ToolError,
    ToolErrorCode,
    ToolErrorDisposition,
)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (ToolErrorCode.TOOL_ARGUMENT_VALIDATION_FAILED, ToolErrorDisposition.RECOVERABLE),
        (ToolErrorCode.TOOL_NOT_FOUND, ToolErrorDisposition.FATAL),
        (ToolErrorCode.TOOL_NOT_ALLOWED, ToolErrorDisposition.FATAL),
        (ToolErrorCode.TOOL_OUTPUT_VALIDATION_FAILED, ToolErrorDisposition.FATAL),
        (ToolErrorCode.TOOL_EXECUTION_FAILED, ToolErrorDisposition.FATAL),
    ],
)
def test_tool_error_dispositions(code: ToolErrorCode, expected: ToolErrorDisposition) -> None:
    assert ToolError(code=code, message="test").disposition is expected


def test_base_url_is_normalized_as_api_root() -> None:
    provider = OpenAICompatibleProvider(
        base_url="https://llm.example/v1/", api_key="secret", model="model"
    )
    assert provider.base_url == "https://llm.example/v1"


@pytest.mark.parametrize(
    "base_url",
    [
        "llm.example/v1",
        "https://llm.example/v1/chat/completions",
        "https://llm.example/v1/chat/completions/",
        "https://llm.example/v1?token=secret",
    ],
)
def test_invalid_base_url_is_rejected(base_url: str) -> None:
    with pytest.raises(ValueError):
        OpenAICompatibleProvider(base_url=base_url, api_key="secret", model="model")


def test_runtime_factory_is_explicit_and_fail_closed() -> None:
    factory = AgentRuntimeFactory()
    with pytest.raises(ValueError, match="not configured"):
        factory.get(RuntimeBackend.LANGGRAPH)


async def test_startup_reconciliation_marks_only_stale_tasks(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'reconcile.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    bus = EventBus()
    async with factory() as session:
        conversation = await ConversationRepository(session).create(
            user_id="dev-user-001", title="Reconcile"
        )
        tasks = TaskRepository(session)
        pending = await tasks.create(
            conversation_id=conversation.conversation_id,
            user_id="dev-user-001",
            task_type="MINIMAL_AGENT_RUN",
            input_data={},
            runtime_backend=RuntimeBackend.MANUAL,
        )
        running = await tasks.create(
            conversation_id=conversation.conversation_id,
            user_id="dev-user-001",
            task_type="MINIMAL_AGENT_RUN",
            input_data={},
            runtime_backend=RuntimeBackend.LANGGRAPH,
        )
        completed = await tasks.create(
            conversation_id=conversation.conversation_id,
            user_id="dev-user-001",
            task_type="MINIMAL_AGENT_RUN",
            input_data={},
        )
        await tasks.transition(running, TaskStatus.RUNNING)
        await tasks.transition(completed, TaskStatus.COMPLETED)
        pending.next_run_at = None
        running.next_run_at = None
        ids = (pending.task_id, running.task_id, completed.task_id)
        await session.commit()

    assert await TaskReconciliationService(factory, bus).reconcile() == 2

    async with factory() as session:
        tasks = TaskRepository(session)
        pending, running, completed = [await tasks.get(task_id) for task_id in ids]
        assert pending is not None and pending.status is TaskStatus.PENDING
        assert running is not None and running.status is TaskStatus.RUNNING
        assert completed is not None and completed.status is TaskStatus.COMPLETED
        for stale in (pending, running):
            assert stale.next_run_at is not None
        events = await EventRepository(session).list_for_conversation(completed.conversation_id)
        assert events == []
    await engine.dispose()


def test_graph_state_contract_contains_no_sensitive_or_runtime_objects() -> None:
    state = {
        "task_id": str(uuid4()),
        "conversation_id": str(uuid4()),
        "runtime_messages": [],
        "step_count": 0,
        "tool_call_count": 0,
        "pending_tool_calls": [],
        "final_answer": None,
        "error": None,
    }
    serialized = str(state).lower()
    for forbidden in (
        "llm_api_key",
        "database_url",
        "httpx",
        "db session",
        "policy",
        "callable",
        "chain_of_thought",
        "reasoning",
        "scratchpad",
    ):
        assert forbidden not in serialized
