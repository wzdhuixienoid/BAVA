from decimal import Decimal

import pytest
from banking_test_helpers import authenticate_workflow, legacy_yellow_authorization
from sqlalchemy import select
from test_plan_conditions import conditional_runtime
from test_subscriptions import create_workflow
from test_transfer_authorization import create_ready_workflow
from test_transfer_operations import operation_runtime
from test_transfer_risk import seed_provider_fact

from banking_api.api.dependencies import get_current_principal
from banking_api.application.operation_service import OperationActionError, OperationService
from banking_api.application.workflow_service import WorkflowActionError, WorkflowService
from banking_api.audit.projection import AuditProjection
from banking_api.domain.principal import Principal
from banking_api.persistence.models import EventModel
from banking_api.security.reauthentication.mock_provider import MockReauthenticationProvider
from banking_api.transfers.provider import TransferProviderFaultMode


async def ready(app, amount="500", fault=TransferProviderFaultMode.SUCCESS):
    _, provider, _, engine = operation_runtime(app, fault_mode=fault)
    workflow = await create_ready_workflow(
        app, app.state.event_bus, engine, user_id="dev-user-001", amount=Decimal(amount)
    )
    return provider, engine, workflow


async def action(app, engine, workflow, name, **kwargs):
    async with app.state.test_session_factory() as session:
        return await getattr(
            WorkflowService(
                session,
                app.state.event_bus,
                engine,
                reauth_provider=MockReauthenticationProvider("audit-test-otp"),
            ),
            name,
        )(
            workflow.workflow_id,
            user_id=workflow.user_id,
            expected_version=workflow.version,
            **kwargs,
        )


async def trace(app, workflow):
    async with app.state.test_session_factory() as session:
        return await AuditProjection(session).get(workflow.source_task_id, workflow.user_id)


async def test_transfer_audit_order_approval_provider_current_state_and_owner_isolation(
    app, client
):
    provider, engine, workflow = await ready(app, "2000")
    workflow = await action(app, engine, workflow, "approve")
    workflow = await authenticate_workflow(app, engine, workflow)
    async with app.state.test_session_factory() as session:
        operation = await OperationService(session, app.state.event_bus, engine).commit_workflow(
            workflow.workflow_id, user_id=workflow.user_id, expected_version=workflow.version
        )
    response = await client.get(f"/api/v1/tasks/{workflow.source_task_id}/audit")
    assert response.status_code == 200
    audit = response.json()
    entries = audit["entries"]
    assert [e["sequence"] for e in entries] == sorted(e["sequence"] for e in entries)
    types = [e["event_type"] for e in entries]
    for before, after in (
        ("conversation.message.created", "task.created"),
        ("workflow.created", "workflow.risk_evaluated"),
        ("approval.created", "approval.approved"),
        ("security.write_check", "operation.created"),
        ("operation.created", "approval.consumed"),
        ("provider.submit_started", "operation.succeeded"),
    ):
        assert types.index(before) < types.index(after)
    assert any(e["event_type"] == "reauth.verified" for e in entries)
    assert audit["write_evidence"]["business_success"] is True
    assert audit["write_evidence"]["provider_ledger_count"] == 1
    assert await provider.transfer_count() == 1
    approval = next(r for r in audit["resources"] if r["resource_type"] == "APPROVAL")
    values = {f["key"]: f["value"] for f in approval["facts"]}
    assert len(values["payload_hash"]) == 64 and "consumed_at" in values
    assert "idempotency_key" in str(audit["resources"])
    # Existing SSE Event convention still excludes the Provider idempotency key.
    assert "idempotency_key" not in str(entries)
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="dev-user-002", issuer="test", subject="other"
    )
    for path in (
        f"tasks/{workflow.source_task_id}/audit",
        f"tasks/{workflow.source_task_id}",
        f"workflows/{workflow.workflow_id}",
        f"operations/{operation.operation_id}",
    ):
        assert (await client.get(f"/api/v1/{path}")).status_code == 404


async def test_risk_escalation_and_approval_mutation_keep_both_authorization_semantics(app):
    _, engine, workflow = await ready(app, "100")
    workflow = await action(app, engine, workflow, "approve")
    workflow = await legacy_yellow_authorization(app, engine, workflow)
    await seed_provider_fact(app, user_id=workflow.user_id, amount="950")
    async with app.state.test_session_factory() as session:
        with pytest.raises(OperationActionError, match="TRANSFER_RISK_REAUTH_REQUIRED"):
            await OperationService(session, app.state.event_bus, engine).prepare_transfer(
                workflow.workflow_id, user_id=workflow.user_id, expected_version=workflow.version
            )
    audit = await trace(app, workflow)
    decisions = [e.risk_decision for e in audit.entries if e.risk_decision]
    assert decisions[0].level.value == "YELLOW" and decisions[-1].level.value == "RED"
    assert decisions[-1].projected_daily_total == Decimal("1050")
    async with app.state.test_session_factory() as session:
        current = await WorkflowService(session, app.state.event_bus, engine).get(
            workflow.workflow_id, user_id=workflow.user_id
        )
    current = await action(app, engine, current, "set_amount", amount=Decimal("700"))
    current = await action(app, engine, current, "approve")
    audit = await trace(app, current)
    approvals = [r for r in audit.resources if r.resource_type == "APPROVAL"]
    assert [r.status for r in approvals] == ["INVALIDATED", "APPROVED"]
    hashes = [{f.key: f.value for f in r.facts}["payload_hash"] for r in approvals]
    assert hashes[0] != hashes[1]
    assert any(e.event_type == "approval.invalidated" for e in audit.entries)


async def test_unknown_reconcile_preserves_historical_unknown(app):
    _, engine, workflow = await ready(app, fault=TransferProviderFaultMode.TIMEOUT_AFTER_ACCEPT)
    workflow = await action(app, engine, workflow, "approve")
    workflow = await authenticate_workflow(app, engine, workflow)
    async with app.state.test_session_factory() as session:
        operation = await OperationService(session, app.state.event_bus, engine).commit_workflow(
            workflow.workflow_id, user_id=workflow.user_id, expected_version=workflow.version
        )
    assert operation.status.value == "UNKNOWN"
    first = await trace(app, workflow)
    assert first.write_evidence.business_success is False
    async with app.state.test_session_factory() as session:
        operation = await OperationService(session, app.state.event_bus, engine).reconcile(
            operation.operation_id, user_id=workflow.user_id, expected_version=operation.version
        )
    audit = await trace(app, workflow)
    kinds = [e.event_type for e in audit.entries]
    unknown = kinds.index("operation.unknown")
    assert (
        unknown
        < kinds.index("operation.reconcile_started", unknown)
        < kinds.index("operation.succeeded")
    )
    assert audit.write_evidence.business_success is True


async def test_mock_reauth_and_guard_denial_never_leak_otp_or_raw_event_secrets(app, client):
    _, engine, workflow = await ready(app, "2000")
    workflow = await action(app, engine, workflow, "approve")
    workflow = await action(app, engine, workflow, "start_reauthentication")
    for _ in range(3):
        with pytest.raises(WorkflowActionError, match="REAUTH_FAILED"):
            await action(
                app,
                engine,
                workflow,
                "verify_reauthentication",
                reauth_id=workflow.reauth_summary.reauth_id,
                verification_code="wrong-secret",
            )
        async with app.state.test_session_factory() as session:
            workflow = await WorkflowService(session, app.state.event_bus, engine).get(
                workflow.workflow_id, user_id=workflow.user_id
            )
    response = await client.post(
        f"/api/v1/workflows/{workflow.workflow_id}/actions/commit",
        json={"expected_version": workflow.version},
    )
    assert response.status_code == 423
    async with app.state.test_session_factory() as session:
        event = await session.scalar(
            select(EventModel).where(EventModel.event_type == "workflow.created")
        )
        event.data_json = {
            **event.data_json,
            "jwt": "eyJ.test.secret",
            "api_key": "sk-leak-marker",
            "reasoning": "hidden-marker",
            "verification_code": "audit-test-otp",
        }
        await session.commit()
    audit = (await client.get(f"/api/v1/tasks/{workflow.source_task_id}/audit")).json()
    exported = str(audit)
    for secret in (
        "audit-test-otp",
        "wrong-secret",
        "eyJ.test.secret",
        "sk-leak-marker",
        "hidden-marker",
    ):
        assert secret not in exported
    assert "Mock Reauthentication" in exported
    assert "security.write_lock_activated" in exported
    assert "security.write_check" in exported and "WRITE_LOCKED" in exported
    assert audit["write_evidence"]["operation_count"] == 0


@pytest.mark.parametrize("threshold,outcome", [("3000", "TRUE"), ("999999", "FALSE")])
async def test_condition_audit_source_hash_and_false_zero_write(app, client, threshold, outcome):
    runner, _, _, _, task_id = await conditional_runtime(app, client, threshold=threshold)
    await runner.run(task_id)
    response = await client.get(f"/api/v1/tasks/{task_id}/audit")
    assert response.status_code == 200
    audit = response.json()
    decisions = [e["condition_decision"] for e in audit["entries"] if e["condition_decision"]]
    assert decisions[-1]["outcome"] == outcome
    assert len(decisions[-1]["source_output_hash"]) == 64
    if outcome == "FALSE":
        assert audit["write_evidence"]["skipped_write_step_ids"]
        assert audit["write_evidence"]["no_write_started"] is True
        for key in (
            "workflow_count",
            "approval_count",
            "operation_count",
            "provider_ledger_count",
            "provider_submission_count",
        ):
            assert audit["write_evidence"][key] == 0


async def test_detected_only_audit_proves_rejection_with_zero_provider_write(app, client):
    _, workflow = await create_workflow(app, "晨光健身")
    response = await client.get(f"/api/v1/tasks/{workflow.source_task_id}/audit")
    audit = response.json()
    assert "SUBSCRIPTION_NOT_MANAGED" in str(audit)
    assert "DETECTED_ONLY" in str(audit)
    assert audit["write_evidence"]["approval_count"] == 0
    assert audit["write_evidence"]["operation_count"] == 0
    assert audit["write_evidence"]["provider_submission_count"] == 0
    for action_name in ("approve", "commit"):
        response = await client.post(
            f"/api/v1/workflows/{workflow.workflow_id}/actions/{action_name}",
            json={"expected_version": workflow.version},
        )
        assert response.status_code == 422


async def test_subscription_audit_yellow_controls_and_final_provider_cancellation(app, client):
    runtime, workflow = await create_workflow(app, "星幕视频")
    _, provider, engine, subscription_engine, _, _ = runtime
    async with app.state.test_session_factory() as session:
        workflow = await WorkflowService(
            session, app.state.event_bus, engine, subscription_engine=subscription_engine
        ).approve(workflow.workflow_id, user_id=workflow.user_id, expected_version=workflow.version)
    async with app.state.test_session_factory() as session:
        await OperationService(
            session, app.state.event_bus, engine, subscription_engine=subscription_engine
        ).commit_workflow(
            workflow.workflow_id, user_id=workflow.user_id, expected_version=workflow.version
        )
    audit = (await client.get(f"/api/v1/tasks/{workflow.source_task_id}/audit")).json()
    facts = {f["key"]: f["value"] for e in audit["entries"] for f in e["facts"]}
    assert facts["risk_level"] == "YELLOW"
    assert facts["required_approval"] == "True"
    assert facts["required_reauthentication"] == "False"
    assert "MANAGED" in str(audit) and "CANCELLED" in str(audit["resources"])
    assert audit["write_evidence"]["business_success"] is True
    assert audit["write_evidence"]["provider_ledger_count"] == 1
    assert await provider.cancellation_count() == 1
