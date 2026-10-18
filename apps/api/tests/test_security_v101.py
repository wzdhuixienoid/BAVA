import base64
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import delete, select
from test_routing_integration import (
    accept,
    build_routed_runner,
    load_task_and_events,
    route_response,
)
from test_runtime_parity import build_runtime, request
from test_transfer_authorization import create_ready_workflow
from test_transfer_operations import operation_runtime

from banking_api.application.workflow_service import WorkflowService
from banking_api.config.settings import Settings, get_settings
from banking_api.domain.enums import MessageRole
from banking_api.llm.models import LLMResponse, LLMToolCall
from banking_api.persistence.models import (
    DomainActionAuditModel,
    MessageModel,
    SubscriptionReadConsentModel,
    TotpCredentialModel,
)
from banking_api.runtime.grounding import NO_VERIFIED_FACTS
from banking_api.security.reauthentication.totp_provider import (
    TotpCredentialService,
    TotpReauthenticationProvider,
    totp_code,
)
from banking_api.subscriptions.provider import MockSubscriptionProvider
from banking_api.workflows.transfer.risk import TransferRiskPolicy


@pytest.mark.parametrize("backend", ["manual", "langgraph"])
@pytest.mark.parametrize(
    "fabrication",
    [
        "工资卡余额999999.00元，转账已经成功到账。",
        "账户已经冻结，全部资金已经转出。",
    ],
)
async def test_model_cannot_publish_financial_claims_without_facts(backend, fabrication):
    runtime, _ = build_runtime(backend, [LLMResponse(content=fabrication)])
    result = await runtime.run(request("工资卡余额是多少？"))
    assert result.answer == NO_VERIFIED_FACTS
    assert not result.state.successful_tool_results


@pytest.mark.parametrize("backend", ["manual", "langgraph"])
async def test_claims_cannot_override_successful_balance_evidence(backend):
    runtime, _ = build_runtime(
        backend,
        [
            LLMResponse(
                tool_calls=[
                    LLMToolCall(
                        id="fact",
                        name="get_balance",
                        arguments={"account_id": "acc_salary"},
                    )
                ]
            ),
            LLMResponse(content="工资卡余额999999元；汇款成功到账。"),
        ],
    )
    result = await runtime.run(request("工资卡余额是多少？"))
    assert "23,864.52" in result.answer
    assert "999999" not in result.answer and "到账" not in result.answer


async def test_product_persists_safe_response_instead_of_model_fabrication(app):
    conversation, accepted = await accept(app, "工资卡余额是多少？")
    runner, _ = build_routed_runner(
        app,
        [
            route_response("PERSONAL_BANKING"),
            LLMResponse(content="余额999999元，转账已成功到账。"),
        ],
    )
    await runner.run(accepted.task_id)
    task, _ = await load_task_and_events(app, accepted.task_id)
    async with app.state.test_session_factory() as session:
        answer = await session.scalar(
            select(MessageModel).where(
                MessageModel.conversation_id == conversation.conversation_id,
                MessageModel.role == MessageRole.ASSISTANT,
            )
        )
    assert task.output["tool_calls"] == 0
    assert answer.content == NO_VERIFIED_FACTS


@pytest.mark.parametrize(
    "successful,inflight,amount,level",
    [
        ("0", "0", "199.99", "YELLOW"),
        ("0", "0", "200.00", "RED"),
        ("0", "0", "200.01", "RED"),
        ("900", "0", "100", "YELLOW"),
        ("900", "0", "100.01", "RED"),
        ("0", "900", "100.01", "RED"),
    ],
)
def test_competition_daily_threshold(successful, inflight, amount, level):
    now = datetime.now(UTC)
    risk = TransferRiskPolicy().evaluate(
        requested_amount=Decimal(amount),
        currency="CNY",
        business_date=now.date(),
        successful_transfer_total_today=Decimal(successful),
        in_flight_transfer_exposure_today=Decimal(inflight),
        evaluated_at=now,
    )
    assert risk.level.value == level
    assert risk.required_reauthentication is (level == "RED")


async def test_subscription_facts_require_owner_confirmation_and_expire(app, client):
    async with app.state.test_session_factory() as session:
        await session.execute(delete(SubscriptionReadConsentModel))
        await session.commit()
    assert (await client.get("/api/v1/subscriptions")).status_code == 428
    assert (
        await client.post("/api/v1/security/subscription-read-consent", json={"confirmed": False})
    ).status_code == 422
    assert (
        await client.post("/api/v1/security/subscription-read-consent", json={"confirmed": True})
    ).status_code == 200
    assert (await client.get("/api/v1/subscriptions")).status_code == 200
    async with app.state.test_session_factory() as session:
        grant = await session.get(SubscriptionReadConsentModel, "dev-user-001")
        grant.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    assert (await client.get("/api/v1/subscriptions")).status_code == 428


async def test_direct_cancel_audit_is_persistent_idempotent_and_owner_scoped(app, client):
    app.state.subscription_provider = MockSubscriptionProvider(
        app.state.test_session_factory,
        app.state.mock_bank,
    )
    action = {"confirmed": True, "expected_version": 0, "idempotency_key": str(uuid4())}
    assert (
        await client.post("/api/v1/subscriptions/sub_video/cancel", json=action)
    ).status_code == 200
    assert (
        await client.post("/api/v1/subscriptions/sub_video/cancel", json=action)
    ).status_code == 200
    traces = (await client.get("/api/v1/security/audit")).json()
    assert len(traces) == 1
    assert traces[0]["outcome"] == "SUCCEEDED"
    assert [e["stage"] for e in traces[0]["evidence"]] == [
        "user_confirmation",
        "security.write_check",
        "contract.validation",
        "provider.result",
    ]
    from banking_api.api.dependencies import get_current_principal
    from banking_api.domain.principal import Principal

    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="other-user",
        issuer="test",
        subject="other-user",
    )
    try:
        assert (await client.get("/api/v1/security/audit")).json() == []
        assert (
            await client.get("/api/v1/security/audit/" + traces[0]["trace_id"])
        ).status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_principal)


@pytest.fixture
def totp_settings(monkeypatch):
    monkeypatch.setenv("REAUTH_PROVIDER", "totp")
    monkeypatch.setenv("MFA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "unix,expected",
    [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
        (20000000000, "65353130"),
    ],
)
def test_totp_rfc6238_vectors(unix, expected):
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert totp_code(secret, unix // 30, digits=8) == expected


async def test_totp_enrollment_encrypts_secret_and_audit_does_not_leak(app, client, totp_settings):
    started = (await client.post("/api/v1/security/mfa/enrollment", json={})).json()
    counter = int(datetime.now(UTC).timestamp()) // 30
    response = await client.post(
        "/api/v1/security/mfa/enrollment/confirm",
        json={
            "code": totp_code(started["secret"], counter),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"method": "totp", "enrolled": True}
    async with app.state.test_session_factory() as session:
        credential = await session.get(TotpCredentialModel, "dev-user-001")
        assert credential.secret_ciphertext != started["secret"]
        assert not credential.pending_ciphertext
        evidence = list(await session.scalars(select(DomainActionAuditModel)))
        assert started["secret"] not in json.dumps([e.evidence for e in evidence])
    assert (await client.post("/api/v1/security/mfa/enrollment", json={})).status_code == 409


async def test_totp_challenge_is_bound_and_code_cannot_be_replayed(app, totp_settings):
    _, _, _, engine = operation_runtime(app)
    user_id = "dev-user-001"
    now = datetime.now(UTC)
    async with app.state.test_session_factory() as session:
        svc = TotpCredentialService(session, totp_settings, clock=lambda: now)
        enrollment = await svc.begin(user_id)
        await svc.confirm(user_id, totp_code(enrollment["secret"], int(now.timestamp()) // 30))
        await session.commit()
    workflow = await create_ready_workflow(app, app.state.event_bus, engine, user_id=user_id)
    later = now + timedelta(seconds=30)
    async with app.state.test_session_factory() as session:
        svc = WorkflowService(session, app.state.event_bus, engine, clock=lambda: later)
        workflow = await svc.approve(
            workflow.workflow_id, user_id=user_id, expected_version=workflow.version
        )
        workflow = await svc.start_reauthentication(
            workflow.workflow_id, user_id=user_id, expected_version=workflow.version
        )
        from banking_api.persistence.models import ReauthenticationModel

        challenge = await session.get(ReauthenticationModel, workflow.reauth_summary.reauth_id)
        verifier = TotpReauthenticationProvider(session, totp_settings, clock=lambda: later)
        code = totp_code(enrollment["secret"], int(later.timestamp()) // 30)
        values = dict(
            user_id=user_id,
            workflow_id=workflow.workflow_id,
            approval_id=challenge.approval_id,
            provider_reference=challenge.provider_reference,
            verification_code=code,
        )
        assert not await verifier.verify(**dict(values, workflow_id=uuid4()))
        assert await verifier.verify(**values)
        assert not await verifier.verify(**values)
        await session.commit()


async def test_enrollment_bruteforce_is_locked(app, totp_settings):
    from banking_api.security.reauthentication.totp_provider import MfaError

    async with app.state.test_session_factory() as session:
        svc = TotpCredentialService(session, totp_settings)
        await svc.begin("dev-user-001")
        for _ in range(3):
            with pytest.raises(MfaError):
                await svc.confirm("dev-user-001", "bad")
        with pytest.raises(MfaError, match="锁定"):
            await svc.begin("dev-user-001")
        await session.commit()


def test_production_cannot_use_mock_or_unencrypted_totp():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_environment="production",
            auth_mode="oidc",
            oidc_issuer="https://issuer.test",
            oidc_audience="banking",
            reauth_provider="mock",
        )
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None, auth_mode="development", reauth_provider="totp", mfa_encryption_key=""
        )


async def test_report_semantics_cannot_publish_model_fabrications_with_valid_evidence_refs():
    from test_reports import golden_snapshot, narrative_response

    from banking_api.llm.fake_provider import FakeLLMProvider
    from banking_api.skill_runtime.executor import SkillExecutor

    draft = json.loads(narrative_response().content)
    draft["headline"] = "银行卡已挂失"
    draft["insights"][0]["narrative"] = "全部资金已经转出"
    draft["insights"][1]["narrative"] = "本期消费低于比较期间"
    report = await SkillExecutor(
        FakeLLMProvider([LLMResponse(content=json.dumps(draft, ensure_ascii=False))])
    ).execute(golden_snapshot())
    visible = report.model_dump_json()
    assert "挂失" not in visible and "资金已经转出" not in visible
    assert "本期消费高于比较期间" in visible
