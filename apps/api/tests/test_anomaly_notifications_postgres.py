# ruff: noqa: F811
import asyncio
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select
from test_anomaly_notifications import runtime, spike_rows
from test_postgres_integration import postgres_factory  # noqa: F401

from banking_api.persistence.models import NotificationModel
from banking_api.runtime.anomaly_notification_worker import AnomalyNotificationWorker

pytestmark = pytest.mark.postgres


async def test_two_scanners_insert_one_notice_and_keep_deleted_dedup(app, postgres_factory):
    app.state.test_session_factory = postgres_factory
    bank, clock, first = runtime(app)
    bank._transactions = spike_rows()
    second = AnomalyNotificationWorker(postgres_factory, bank, clock=lambda: clock[0])
    assert sum(await asyncio.gather(first.run_once(), second.run_once())) == 1
    async with postgres_factory() as session:
        assert await session.scalar(select(func.count()).select_from(NotificationModel)) == 1
        row = await session.scalar(select(NotificationModel))
        assert row.anomaly_snapshot["anomalies"][0]["transaction_id"] == "spike"
        row.deleted_at = clock[0]
        await session.commit()
    assert sum(await asyncio.gather(first.run_once(), second.run_once())) == 0


async def test_upgrade_keeps_existing_notifications(app, postgres_factory):
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

    async with postgres_factory() as session:
        row = NotificationModel(
            user_id="dev-user-001", source_key="old-notice", title="旧提醒", message="旧消息保留"
        )
        session.add(row)
        await session.commit()
        identity = row.notification_id
    try:
        await migrate("downgrade", "0035")
        await migrate("upgrade", "head")
        async with postgres_factory() as session:
            row = await session.get(NotificationModel, identity)
            assert row.message == "旧消息保留" and row.anomaly_snapshot is None
    finally:
        await migrate("upgrade", "head")


async def test_downgrade_preserves_generated_evidence(app, postgres_factory):
    app.state.test_session_factory = postgres_factory
    bank, _, worker = runtime(app)
    bank._transactions = spike_rows()
    assert await worker.run_once() == 1
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        "downgrade",
        "0035",
        cwd=Path(__file__).parents[1],
        env={**os.environ, "DATABASE_URL": os.environ["TEST_DATABASE_URL"]},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, error = await process.communicate()
    assert process.returncode != 0 and b"Refusing destructive downgrade" in error
    async with postgres_factory() as session:
        notice = await session.scalar(select(NotificationModel))
        assert notice.anomaly_snapshot["anomalies"][0]["transaction_id"] == "spike"
