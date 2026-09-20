import os
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from banking_api.agents.minimal_banking_agent import MINIMAL_BANKING_AGENT
from banking_api.application.conversation_service import ConversationService
from banking_api.application.task_service import TaskService
from banking_api.context.builder import ContextBuilder
from banking_api.domain.enums import TaskStatus
from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.llm.models import LLMResponse, LLMToolCall
from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import EventModel
from banking_api.policy.service import PolicyService
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.runtime.agent_runtime import AgentRuntime
from banking_api.runtime.event_bus import EventBus
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
        assert revision == "0002"
        assert progress_column == "progress_message"
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
    await InProcessTaskRunner(factory, bus, runtime).run(accepted.task_id)

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

    assert task.task_type == "MINIMAL_AGENT_RUN"
    assert task.status is TaskStatus.COMPLETED
    assert task.version == 7
    assert isinstance(task.input, dict)
    assert task.output == {
        "message_id": str(detail.messages[-1].message_id),
        "steps": 3,
        "tool_calls": 2,
    }
    assert detail.messages[-1].content == "工资卡余额为 23,864.52 元。"
    assert [event.sequence for event in events] == sorted(event.sequence for event in events)
    assert [event.event_type for event in events].count("tool.call.completed") == 2
    assert events[-2].event_type == "task.completed"
    assert events[-1].event_type == "conversation.message.completed"
