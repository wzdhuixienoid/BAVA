from decimal import Decimal

import pytest
from sqlalchemy import func, select
from test_security_v101 import totp_settings as totp_settings
from test_transfer_authorization import create_ready_workflow
from test_transfer_operations import operation_runtime

from banking_api.api.dependencies import get_current_principal
from banking_api.application.operation_service import OperationActionError, OperationService
from banking_api.application.workflow_service import WorkflowService
from banking_api.config.settings import get_settings
from banking_api.domain.principal import Principal
from banking_api.persistence.models import OperationModel


def change(amount, *, version=0, code=None):
    return {
        "amount": amount,
        "expected_version": version,
        "confirmed": True,
        "verification_code": get_settings().mock_reauth_code if code is None else code,
    }


async def test_personal_limit_capped_at_200_verified_audited_and_isolated(app, client):
    initial = (await client.get("/api/v1/security/transfer-preference")).json()
    assert Decimal(initial["passwordless_limit"]) == Decimal("200")
    invalid = dict(change("50"), confirmed=False)
    assert (
        await client.post("/api/v1/security/transfer-preference", json=invalid)
    ).status_code == 422
    for value in ("200.01", "-0.01", "0.001", "NaN", "Infinity"):
        response = await client.post("/api/v1/security/transfer-preference", json=change(value))
        assert response.status_code == 422
    assert (
        await client.post(
            "/api/v1/security/transfer-preference", json=change("50", code="incorrect")
        )
    ).status_code == 409
    assert (await client.get("/api/v1/security/transfer-preference")).json() == initial
    saved = await client.post("/api/v1/security/transfer-preference", json=change("50"))
    assert saved.status_code == 200, saved.text
    assert Decimal(saved.json()["passwordless_limit"]) == Decimal("50")
    assert saved.json()["version"] == 1
    assert (
        await client.post("/api/v1/security/transfer-preference", json=change("80"))
    ).status_code == 409
    traces = (await client.get("/api/v1/security/audit")).json()
    assert any(row["action"] == "transfer.passwordless_limit.update" for row in traces)
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="another-owner",
        issuer="test",
        subject="another-owner",
    )
    try:
        other = (await client.get("/api/v1/security/transfer-preference")).json()
        assert Decimal(other["passwordless_limit"]) == Decimal("200") and other["version"] == 0
    finally:
        app.dependency_overrides.pop(get_current_principal)


@pytest.mark.parametrize("amount,expected", [("49.99", "YELLOW"), ("50", "RED"), ("50.01", "RED")])
async def test_single_transfer_strictly_below_personal_limit_is_yellow(
    app, client, amount, expected
):
    assert (
        await client.post("/api/v1/security/transfer-preference", json=change("50"))
    ).status_code == 200
    _, _, _, engine = operation_runtime(app)
    workflow = await create_ready_workflow(
        app, app.state.event_bus, engine, user_id="dev-user-001", amount=Decimal(amount)
    )
    assert workflow.risk_level.value == expected
    assert workflow.risk_decision.passwordless_limit == Decimal("50")


async def test_setting_zero_disables_exemption(app, client):
    assert (
        await client.post("/api/v1/security/transfer-preference", json=change("0"))
    ).status_code == 200
    _, _, _, engine = operation_runtime(app)
    workflow = await create_ready_workflow(
        app, app.state.event_bus, engine, user_id="dev-user-001", amount=Decimal("0.01")
    )
    assert workflow.risk_level.value == "RED"


async def test_lowered_limit_is_rechecked_at_commit_before_creating_operation(app, client):
    _, _, _, engine = operation_runtime(app)
    workflow = await create_ready_workflow(
        app, app.state.event_bus, engine, user_id="dev-user-001", amount=Decimal("150")
    )
    assert workflow.risk_level.value == "YELLOW"
    async with app.state.test_session_factory() as session:
        approved = await WorkflowService(session, app.state.event_bus, engine).approve(
            workflow.workflow_id,
            user_id=workflow.user_id,
            expected_version=workflow.version,
        )
    assert (
        await client.post("/api/v1/security/transfer-preference", json=change("100"))
    ).status_code == 200
    async with app.state.test_session_factory() as session:
        with pytest.raises(OperationActionError, match="TRANSFER_RISK_REAUTH_REQUIRED"):
            await OperationService(session, app.state.event_bus, engine).prepare_transfer(
                approved.workflow_id,
                user_id=approved.user_id,
                expected_version=approved.version,
            )
    async with app.state.test_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(OperationModel)) == 0


async def test_limit_edit_failures_trigger_write_lock(app, client):
    for _ in range(3):
        assert (
            await client.post("/api/v1/security/transfer-preference", json=change("50", code="bad"))
        ).status_code == 409
    assert (
        await client.post("/api/v1/security/transfer-preference", json=change("50"))
    ).status_code == 423
    assert (await client.get("/api/v1/security/transfer-preference")).status_code == 200


async def test_limit_update_uses_real_authenticator_and_consumes_code_once(
    app, client, totp_settings
):
    from datetime import UTC, datetime, timedelta

    from banking_api.security.reauthentication.totp_provider import TotpCredentialService, totp_code

    now = datetime.now(UTC)
    prior = now - timedelta(seconds=30)
    async with app.state.test_session_factory() as session:
        service = TotpCredentialService(session, totp_settings, clock=lambda: prior)
        enrollment = await service.begin("dev-user-001")
        await service.confirm(
            "dev-user-001", totp_code(enrollment["secret"], int(prior.timestamp()) // 30)
        )
        await session.commit()
    invalid = await client.post(
        "/api/v1/security/transfer-preference", json=change("50", code="not-a-totp")
    )
    assert invalid.status_code == 409
    code = totp_code(enrollment["secret"], int(now.timestamp()) // 30)
    saved = await client.post("/api/v1/security/transfer-preference", json=change("50", code=code))
    assert saved.status_code == 200, saved.text
    replay = await client.post(
        "/api/v1/security/transfer-preference", json=change("80", version=1, code=code)
    )
    assert replay.status_code == 409
    assert (await client.get("/api/v1/security/transfer-preference")).json()[
        "passwordless_limit"
    ] == "50.00"
