# ruff: noqa: F811
import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from test_aa_collections import aa_runtime, published_request
from test_aa_deletion import OWNER, cancel_all
from test_postgres_integration import postgres_factory  # noqa: F401

from banking_api.application.aa_service import AAService
from banking_api.application.operation_service import OperationActionError
from banking_api.persistence.models import AARequestModel, AAShareModel, EventModel

pytestmark = pytest.mark.postgres


@pytest.fixture
async def pg_app(app, postgres_factory):
    app.state.test_session_factory = postgres_factory
    return app


async def test_concurrent_delete_one_version_one_audit(pg_app):
    bank, _, engine = await aa_runtime(pg_app)
    row = await cancel_all(pg_app, bank, engine, await published_request(pg_app, bank, engine))

    async def remove():
        async with pg_app.state.test_session_factory() as session:
            try:
                await AAService(session, pg_app.state.event_bus, engine, bank).delete_cancelled(
                    UUID(row["request_id"]), OWNER, row["version"]
                )
                return "deleted"
            except OperationActionError as exc:
                return str(exc)

    outcomes = await asyncio.wait_for(asyncio.gather(remove(), remove()), 10)
    assert sorted(outcomes) == ["AA_VERSION_CONFLICT", "deleted"]
    async with pg_app.state.test_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(AARequestModel)) == 1
        assert await session.scalar(select(func.count()).select_from(AAShareModel)) == 3
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EventModel)
                .where(EventModel.event_type == "aa.deleted_from_list")
            )
            == 1
        )


async def test_0035_upgrade_preserves_existing_cancelled_request(pg_app):
    bank, _, engine = await aa_runtime(pg_app)
    row = await cancel_all(pg_app, bank, engine, await published_request(pg_app, bank, engine))
    request_id = UUID(row["request_id"])

    async def migrate(*args):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "alembic",
            *args,
            cwd=Path(__file__).parents[1],
            env={**os.environ, "DATABASE_URL": os.environ["TEST_DATABASE_URL"]},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        output = await process.communicate()
        assert process.returncode == 0, output

    try:
        await migrate("downgrade", "0034")
        async with pg_app.state.test_session_factory() as session:
            assert await session.scalar(text("SELECT version_num FROM alembic_version")) == "0034"
            assert await session.scalar(text("SELECT count(*) FROM aa_requests")) == 1
        await migrate("upgrade", "head")
        async with pg_app.state.test_session_factory() as session:
            service = AAService(session, pg_app.state.event_bus, engine, bank)
            upgraded = await service.get(request_id, OWNER)
            assert upgraded["snapshot"] == row["snapshot"]
            assert upgraded["can_delete"] and not upgraded["deleted_from_list"]
            await service.delete_cancelled(request_id, OWNER, upgraded["version"])
            assert await service.list(OWNER) == []
    finally:
        await migrate("upgrade", "head")
