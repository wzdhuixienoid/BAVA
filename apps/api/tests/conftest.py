import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

os.environ.setdefault("APP_ENVIRONMENT", "test")
os.environ.setdefault("AUTH_MODE", "development")
os.environ.setdefault("REAUTH_PROVIDER", "mock")
# Tests must not inherit optional demo modes from the developer's local .env.
# Dedicated Mock and scheduling tests enable these flags explicitly.
os.environ.setdefault("MOCK_PARTICIPANT_LOGIN_ENABLED", "false")
os.environ.setdefault("MOCK_SCHEDULED_TRANSFERS_ENABLED", "false")
os.environ["MOCK_WEALTH_ENABLED"] = "false"
os.environ.setdefault("MOCK_SUBSCRIPTION_BILLING_ENABLED", "false")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from banking_api.agents.personal_banking_agent import PERSONAL_BANKING_ACCOUNT_AGENT
from banking_api.context.builder import ContextBuilder
from banking_api.domain.enums import RuntimeBackend
from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.llm.models import LLMResponse
from banking_api.main import create_app
from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.database import Base, get_session
from banking_api.persistence.models import SubscriptionReadConsentModel
from banking_api.policy.service import PolicyService
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.runtime.agent_runtime import AgentRuntime
from banking_api.runtime.runtime_factory import AgentRuntimeFactory
from banking_api.runtime.task_runner import InProcessTaskRunner
from banking_api.tools.banking import build_get_balance_tool, build_list_accounts_tool
from banking_api.tools.executor import ToolExecutor


@pytest.fixture
async def app(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    # Most business regressions start after the owner's explicit query consent.
    # Dedicated consent tests remove this fixture grant and exercise the 428 / confirm path.
    async with factory() as session:
        session.add(
            SubscriptionReadConsentModel(
                user_id="dev-user-001",
                approved_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
        await session.commit()

    application = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    application.dependency_overrides[get_session] = override_session
    registry = ToolRegistry()
    bank = MockBankService()
    registry.register(build_list_accounts_tool(bank))
    registry.register(build_get_balance_tool(bank))

    def make_runner(responses, *, max_steps=6, max_tool_calls=4):
        runtime = AgentRuntime(
            provider=FakeLLMProvider(responses),
            registry=registry,
            executor=ToolExecutor(registry, PolicyService()),
            context_builder=ContextBuilder(),
            agent=PERSONAL_BANKING_ACCOUNT_AGENT,
            max_steps=max_steps,
            max_tool_calls=max_tool_calls,
        )
        runtime_factory = AgentRuntimeFactory()
        runtime_factory.register(RuntimeBackend.MANUAL, runtime)
        return InProcessTaskRunner(
            factory,
            application.state.event_bus,
            runtime_factory,
            default_backend=RuntimeBackend.MANUAL,
        )

    application.state.tool_registry = registry
    application.state.task_runner = make_runner([LLMResponse(content="已收到你的消息。")])
    application.state.test_make_runner = make_runner
    application.state.test_session_factory = factory
    yield application
    await engine.dispose()


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        yield test_client
