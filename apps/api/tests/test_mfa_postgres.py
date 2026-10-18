import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from test_postgres_integration import postgres_factory as postgres_factory
from test_security_v101 import totp_settings as totp_settings
from test_transfer_authorization import create_ready_workflow
from test_transfer_operations import operation_runtime

from banking_api.application.workflow_service import WorkflowService
from banking_api.config.settings import get_settings
from banking_api.persistence.models import ReauthenticationModel, TotpCredentialModel
from banking_api.security.reauthentication.totp_provider import (
    TotpCredentialService,
    TotpReauthenticationProvider,
    totp_code,
)

pytestmark = pytest.mark.postgres


async def test_concurrent_challenges_cannot_reuse_same_authenticator_code(
    app,
    postgres_factory,
    totp_settings,
):
    app.state.test_session_factory = postgres_factory
    _, _, _, engine = operation_runtime(app)
    now = datetime.now(UTC)
    user = "dev-user-001"
    async with postgres_factory() as session:
        credentials = TotpCredentialService(session, totp_settings, clock=lambda: now)
        enrollment = await credentials.begin(user)
        await credentials.confirm(user, totp_code(enrollment["secret"], int(now.timestamp()) // 30))
        await session.commit()
    later = now + timedelta(seconds=30)
    challenges = []
    for _ in range(2):
        workflow = await create_ready_workflow(app, app.state.event_bus, engine, user_id=user)
        async with postgres_factory() as session:
            svc = WorkflowService(session, app.state.event_bus, engine, clock=lambda: later)
            approved = await svc.approve(
                workflow.workflow_id, user_id=user, expected_version=workflow.version
            )
            challenged = await svc.start_reauthentication(
                workflow.workflow_id, user_id=user, expected_version=approved.version
            )
            challenge = await session.get(
                ReauthenticationModel, challenged.reauth_summary.reauth_id
            )
            challenges.append(
                (workflow.workflow_id, challenge.approval_id, challenge.provider_reference)
            )
    code = totp_code(enrollment["secret"], int(later.timestamp()) // 30)

    async def verify(challenge):
        async with postgres_factory() as session:
            provider = TotpReauthenticationProvider(session, totp_settings, clock=lambda: later)
            result = await provider.verify(
                user_id=user,
                workflow_id=challenge[0],
                approval_id=challenge[1],
                provider_reference=challenge[2],
                verification_code=code,
            )
            await session.commit()
            return result

    assert sorted(await asyncio.gather(*(verify(c) for c in challenges))) == [False, True]


async def test_migration_refuses_to_drop_enrolled_authenticator(postgres_factory):
    async with postgres_factory() as session:
        session.add(
            TotpCredentialModel(user_id="retained-credential", last_counter=-1, failure_count=0)
        )
        await session.commit()
    settings = get_settings()
    previous = settings.database_url
    settings.database_url = postgres_factory.kw["bind"].url.render_as_string(hide_password=False)
    api = Path(__file__).parents[1]
    config = Config(str(api / "alembic.ini"))
    config.set_main_option("script_location", str(api / "migrations"))
    try:
        with pytest.raises(RuntimeError, match="Refusing downgrade"):
            await asyncio.to_thread(command.downgrade, config, "0036")
        async with postgres_factory() as session:
            assert await session.scalar(select(func.count()).select_from(TotpCredentialModel)) == 1
            assert await session.scalar(text("SELECT version_num FROM alembic_version")) == "0038"
    finally:
        settings.database_url = previous
