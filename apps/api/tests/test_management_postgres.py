import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from banking_api.application.conversation_service import (
    ConversationActiveError,
    ConversationNotFoundError,
    ConversationService,
)
from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import (
    ConversationModel,
    MockSubscriptionActionModel,
    MockSubscriptionStateModel,
    TaskModel,
)
from banking_api.runtime.event_bus import EventBus
from banking_api.subscriptions.provider import (
    MockSubscriptionProvider,
    SubscriptionCancellationRequest,
)

pytestmark = pytest.mark.postgres


@pytest.fixture
async def management_factory():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    assert "test" in url.lower(), "Use an isolated test database"
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = f"management-test-{uuid4().hex}"
    yield factory, owner
    async with factory() as session:
        for model in (ConversationModel, MockSubscriptionActionModel, MockSubscriptionStateModel):
            await session.execute(delete(model).where(model.user_id == owner))
        await session.commit()
    await engine.dispose()


async def test_two_provider_connections_serialize_resume(management_factory):
    factory, owner = management_factory
    bank = MockBankService(fixture_user_ids=frozenset({owner}))
    providers = [MockSubscriptionProvider(factory, bank) for _ in range(2)]
    requests = [
        SubscriptionCancellationRequest(
            user_id=owner,
            subscription_id="sub_fitness",
            idempotency_key=uuid4(),
            expected_version=0,
        )
        for _ in providers
    ]
    results = await asyncio.gather(
        *(provider.resume(request) for provider, request in zip(providers, requests, strict=True))
    )
    assert sorted(row.outcome for row in results) == ["ACCEPTED", "FAILED"]
    assert any(row.error_code == "SUBSCRIPTION_VERSION_CONFLICT" for row in results)
    async with factory() as session:
        state = await session.get(MockSubscriptionStateModel, (owner, "sub_fitness"))
        assert state.status == "ACTIVE" and state.version == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(MockSubscriptionActionModel)
                .where(
                    MockSubscriptionActionModel.user_id == owner,
                    MockSubscriptionActionModel.status == "SUCCEEDED",
                )
            )
            == 1
        )


async def test_delete_and_message_share_conversation_lock(management_factory):
    factory, owner = management_factory
    bus = EventBus()
    for _ in range(8):
        async with factory() as session:
            conversation = await ConversationService(session, bus).create(
                user_id=owner, title="并发删除"
            )

        async def remove(cid=conversation.conversation_id):
            async with factory() as session:
                return await ConversationService(session, bus).delete(
                    conversation_id=cid, user_id=owner
                )

        async def send(cid=conversation.conversation_id):
            async with factory() as session:
                return await ConversationService(session, bus).accept_message(
                    conversation_id=cid, user_id=owner, content="查询"
                )

        results = await asyncio.gather(remove(), send(), return_exceptions=True)
        assert isinstance(results[0], ConversationActiveError) or isinstance(
            results[1], ConversationNotFoundError
        )
        async with factory() as session:
            row = await session.get(ConversationModel, conversation.conversation_id)
            if row.deleted_at:
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(TaskModel)
                        .where(TaskModel.conversation_id == row.conversation_id)
                    )
                    == 0
                )
