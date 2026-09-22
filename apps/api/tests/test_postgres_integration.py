import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from banking_api.agents.minimal_banking_agent import MINIMAL_BANKING_AGENT
from banking_api.application.conversation_service import ConversationService
from banking_api.application.task_service import TaskService
from banking_api.context.builder import ContextBuilder
from banking_api.domain.enums import MessageRole, RuntimeBackend, TaskStatus
from banking_api.domain.message import Message
from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.llm.models import LLMResponse, LLMToolCall
from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import EventModel
from banking_api.persistence.repositories.tasks import TaskRepository
from banking_api.policy.service import PolicyService
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.runtime.agent_runtime import AgentRuntime
from banking_api.runtime.base import AgentRunRequest
from banking_api.runtime.event_bus import EventBus
from banking_api.runtime.langgraph.checkpoint import (
    LangGraphCheckpointManager,
    normalize_checkpoint_database_url,
)
from banking_api.runtime.langgraph.graph import LangGraphAgentRuntime
from banking_api.runtime.runtime_factory import AgentRuntimeFactory
from banking_api.runtime.task_reconciliation import TaskReconciliationService
from banking_api.runtime.task_runner import InProcessTaskRunner
from banking_api.tools.banking import build_get_balance_tool, build_list_accounts_tool
from banking_api.tools.executor import ToolExecutor

pytestmark = pytest.mark.postgres
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.fixture
async def postgres_factory():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not configured")
    assert "test" in TEST_DATABASE_URL.lower(), "TEST_DATABASE_URL must name an isolated test DB"
    engine = create_async_engine(TEST_DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.execute(
            text("TRUNCATE events, tasks, messages, conversations RESTART IDENTITY CASCADE")
        )
    yield factory
    async with engine.begin() as connection:
        await connection.execute(
            text("TRUNCATE events, tasks, messages, conversations RESTART IDENTITY CASCADE")
        )
    await engine.dispose()


async def test_postgres_migration_persistence_and_fake_agent_e2e(postgres_factory) -> None:
    factory = postgres_factory
    bus = EventBus()
    async with factory() as session:
        revision = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        progress_column = (
            await session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'tasks' AND column_name = 'progress_message'"
                )
            )
        ).scalar()
        executor_columns = set(
            (
                await session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'tasks' "
                        "AND column_name IN ('executor_type', 'executor_id')"
                    )
                )
            ).scalars()
        )
        assert revision == "0004"
        assert progress_column == "progress_message"
        assert executor_columns == {"executor_type", "executor_id"}
        conversation = await ConversationService(session, bus).create(
            user_id="postgres-test-user", title="PostgreSQL Agent E2E"
        )
    async with factory() as session:
        accepted = await ConversationService(session, bus).accept_message(
            conversation_id=conversation.conversation_id,
            user_id="postgres-test-user",
            content="我的工资卡余额是多少？",
        )

    bank = MockBankService()
    registry = ToolRegistry()
    registry.register(build_list_accounts_tool(bank))
    registry.register(build_get_balance_tool(bank))
    runtime = AgentRuntime(
        provider=FakeLLMProvider(
            [
                LLMResponse(
                    tool_calls=[
                        LLMToolCall(id="call_1", name="list_accounts", arguments={})
                    ]
                ),
                LLMResponse(
                    tool_calls=[
                        LLMToolCall(
                            id="call_2",
                            name="get_balance",
                            arguments={"account_id": "acc_salary"},
                        )
                    ]
                ),
                LLMResponse(content="工资卡余额为 23,864.52 元。"),
            ]
        ),
        registry=registry,
        executor=ToolExecutor(registry, PolicyService()),
        context_builder=ContextBuilder(),
        agent=MINIMAL_BANKING_AGENT,
    )
    runtime_factory = AgentRuntimeFactory()
    runtime_factory.register(RuntimeBackend.MANUAL, runtime)
    await InProcessTaskRunner(factory, bus, runtime_factory).run(accepted.task_id)

    async with factory() as session:
        task = await TaskService(session).get(
            UUID(str(accepted.task_id)), user_id="postgres-test-user"
        )
        detail = await ConversationService(session, bus).get(
            conversation_id=conversation.conversation_id,
            user_id="postgres-test-user",
        )
        events = list(
            (
                await session.execute(
                    select(EventModel)
                    .where(EventModel.task_id == accepted.task_id)
                    .order_by(EventModel.sequence)
                )
            ).scalars()
        )

    assert task.task_type == "BANKING_REQUEST"
    assert task.runtime_backend is RuntimeBackend.MANUAL
    assert task.executor_id == "agent:minimal-banking"
    assert task.status is TaskStatus.COMPLETED
    assert task.version == 8
    assert isinstance(task.input, dict)
    assert task.output == {
        "agent_id": "agent:minimal-banking",
        "assistant_message_id": str(detail.messages[-1].message_id),
        "steps": 3,
        "tool_calls": 2,
    }
    assert detail.messages[-1].content == "工资卡余额为 23,864.52 元。"
    assert [event.sequence for event in events] == sorted(event.sequence for event in events)
    assert [event.event_type for event in events].count("tool.call.completed") == 2
    assert events[-2].event_type == "task.completed"
    assert events[-1].event_type == "conversation.message.completed"


class CountingBankService(MockBankService):
    def __init__(self, counts: dict[str, int]) -> None:
        super().__init__()
        self.counts = counts

    def list_accounts(self):  # type: ignore[no-untyped-def]
        self.counts["list_accounts"] += 1
        return super().list_accounts()

    def get_balance(self, account_id: str):  # type: ignore[no-untyped-def]
        self.counts["get_balance"] += 1
        return super().get_balance(account_id)


def build_langgraph_runtime(provider, bank, checkpointer):  # type: ignore[no-untyped-def]
    registry = ToolRegistry()
    registry.register(build_list_accounts_tool(bank))
    registry.register(build_get_balance_tool(bank))
    return LangGraphAgentRuntime(
        provider=provider,
        registry=registry,
        executor=ToolExecutor(registry, PolicyService()),
        context_builder=ContextBuilder(),
        agent=MINIMAL_BANKING_AGENT,
        checkpointer=checkpointer,
    )


async def test_postgres_checkpoint_persistence_and_resume(postgres_factory) -> None:
    assert TEST_DATABASE_URL is not None
    checkpoint_url = normalize_checkpoint_database_url(TEST_DATABASE_URL)
    task_id = uuid4()
    conversation_id = uuid4()
    message = Message(
        message_id=uuid4(),
        conversation_id=conversation_id,
        role=MessageRole.USER,
        content="我的工资卡余额是多少？",
        created_at=datetime.now(UTC),
    )
    request = AgentRunRequest(
        task_id=task_id,
        conversation_id=conversation_id,
        current_task=message.content,
        conversation_messages=[message],
        authenticated=True,
    )
    counts = {"list_accounts": 0, "get_balance": 0}

    manager_one = LangGraphCheckpointManager(checkpoint_url, strict_msgpack=True)
    saver_one = await manager_one.start()
    runtime_one = build_langgraph_runtime(
        FakeLLMProvider(
            [
                LLMResponse(
                    tool_calls=[
                        LLMToolCall(id="list", name="list_accounts", arguments={})
                    ]
                )
            ]
        ),
        CountingBankService(counts),
        saver_one,
    )
    phase_one = await runtime_one.run_until_tool_checkpoint(request)
    assert phase_one["tool_call_count"] == 1
    assert counts == {"list_accounts": 1, "get_balance": 0}

    async with postgres_factory() as session:
        persisted = (
            await session.execute(
                text("SELECT count(*) FROM checkpoints WHERE thread_id = :thread_id"),
                {"thread_id": str(task_id)},
            )
        ).scalar_one()
    assert persisted > 0
    await manager_one.close()
    del runtime_one

    manager_two = LangGraphCheckpointManager(checkpoint_url, strict_msgpack=True)
    saver_two = await manager_two.start()
    runtime_two = build_langgraph_runtime(
        FakeLLMProvider(
            [
                LLMResponse(
                    tool_calls=[
                        LLMToolCall(
                            id="balance",
                            name="get_balance",
                            arguments={"account_id": "acc_salary"},
                        )
                    ]
                ),
                LLMResponse(content="工资卡余额为 23,864.52 元。"),
            ]
        ),
        CountingBankService(counts),
        saver_two,
    )
    result = await runtime_two.resume(request)
    assert result.answer == "工资卡余额为 23,864.52 元。"
    assert counts == {"list_accounts": 1, "get_balance": 1}
    tuple_ = await saver_two.aget_tuple(
        {"configurable": {"thread_id": str(task_id)}}
    )
    assert tuple_ is not None
    checkpoint_repr = repr(tuple_.checkpoint).lower()
    for forbidden in (
        "llm_api_key",
        "database_url",
        "chain_of_thought",
        "scratchpad",
    ):
        assert forbidden not in checkpoint_repr
    await manager_two.close()


async def test_postgres_startup_reconciliation(postgres_factory) -> None:
    factory = postgres_factory
    bus = EventBus()
    async with factory() as session:
        conversation = await ConversationService(session, bus).create(
            user_id="postgres-test-user", title="Reconciliation"
        )
        tasks = TaskRepository(session)
        pending = await tasks.create(
            conversation_id=conversation.conversation_id,
            task_type="MINIMAL_AGENT_RUN",
            input_data={},
            runtime_backend=RuntimeBackend.LANGGRAPH,
        )
        running = await tasks.create(
            conversation_id=conversation.conversation_id,
            task_type="MINIMAL_AGENT_RUN",
            input_data={},
        )
        completed = await tasks.create(
            conversation_id=conversation.conversation_id,
            task_type="MINIMAL_AGENT_RUN",
            input_data={},
        )
        await tasks.transition(running, TaskStatus.RUNNING)
        await tasks.transition(completed, TaskStatus.COMPLETED)
        ids = [pending.task_id, running.task_id, completed.task_id]
        await session.commit()

    assert await TaskReconciliationService(factory, bus).reconcile() == 2
    async with factory() as session:
        tasks = TaskRepository(session)
        reconciled = [await tasks.get(task_id) for task_id in ids]
        assert [task.status for task in reconciled if task is not None] == [
            TaskStatus.INTERRUPTED,
            TaskStatus.INTERRUPTED,
            TaskStatus.COMPLETED,
        ]
        assert reconciled[0] is not None
        assert reconciled[0].runtime_backend is RuntimeBackend.LANGGRAPH
