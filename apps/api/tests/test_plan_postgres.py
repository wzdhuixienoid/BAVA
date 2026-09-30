import asyncio
import json
from pathlib import Path

import pytest
import test_postgres_integration
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from test_plans import (
    proposal,
)
from test_plans import (
    test_stale_read_worker_cannot_complete_plan_or_message as stale_worker_case,
)
from test_plans import (
    test_waiting_external_unknown_wakes_after_locked_recovery as external_case,
)

from banking_api.api.dependencies import get_session
from banking_api.config.settings import get_settings
from banking_api.persistence.models import PlanModel
from banking_api.persistence.repositories.conversations import ConversationRepository
from banking_api.persistence.repositories.plans import PlanRepository
from banking_api.persistence.repositories.tasks import TaskRepository
from banking_api.planning.validator import PlanValidator

pytestmark = pytest.mark.postgres
postgres_factory = test_postgres_integration.postgres_factory


async def test_postgres_plan_migration_0015_to_0016(postgres_factory):
    settings = get_settings()
    original_url = settings.database_url
    settings.database_url = str(
        postgres_factory.kw["bind"].url.render_as_string(hide_password=False)
    )
    api_dir = Path(__file__).parents[1]
    config = Config(str(api_dir / "alembic.ini"))
    config.set_main_option("script_location", str(api_dir / "migrations"))
    try:
        # The fixture truncates this isolated test database; only the three
        # newly added Plan tables are removed by this downgrade.
        await asyncio.to_thread(command.downgrade, config, "0015")
        async with postgres_factory() as session:
            assert await session.scalar(text("SELECT version_num FROM alembic_version")) == "0015"
            assert await session.scalar(text("SELECT to_regclass('plans')")) is None
        await asyncio.to_thread(command.upgrade, config, "0016")
        async with postgres_factory() as session:
            assert await session.scalar(text("SELECT version_num FROM alembic_version")) == "0016"
            for table in ("plans", "plan_steps", "plan_step_dependencies"):
                assert await session.scalar(text("SELECT to_regclass(:name)"), {"name": table})
    finally:
        settings.database_url = original_url


async def test_postgres_plan_source_task_unique_and_graph_persisted(postgres_factory):
    async with postgres_factory() as session:
        conversation = await ConversationRepository(session).create(
            user_id="plan-user", title="DAG"
        )
        task = await TaskRepository(session).create(
            conversation_id=conversation.conversation_id,
            user_id="plan-user",
            task_type="USER_REQUEST",
            input_data={},
        )
        validated = PlanValidator().parse(json.dumps(proposal()))
        repository = PlanRepository(session)
        plan = await repository.create(
            validated,
            task_id=task.task_id,
            conversation_id=conversation.conversation_id,
            user_id="plan-user",
        )
        await session.commit()
        assert len(await repository.steps(plan.plan_id)) == 2
        assert len(await repository.dependencies(plan.plan_id)) == 1
        with pytest.raises(IntegrityError):
            await repository.create(
                validated,
                task_id=task.task_id,
                conversation_id=conversation.conversation_id,
                user_id="plan-user",
            )
        await session.rollback()
        assert await session.scalar(select(func.count()).select_from(PlanModel)) == 1


async def use_postgres(app, factory):
    app.state.test_session_factory = factory

    async def session_override():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_override


async def test_postgres_plan_fencing_stale_read_worker(app, client, postgres_factory):
    await use_postgres(app, postgres_factory)
    await stale_worker_case(app, client)


async def test_postgres_plan_unknown_locked_recovery_and_wake(app, client, postgres_factory):
    await use_postgres(app, postgres_factory)
    await external_case(app, client)
