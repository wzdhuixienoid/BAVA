from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from test_transfer_authorization import MutableClock, create_ready_workflow

from banking_api.api.dependencies import get_current_principal
from banking_api.application.operation_service import (
    OperationActionError,
    OperationService,
    OperationVersionConflictError,
)
from banking_api.application.workflow_service import WorkflowActionError, WorkflowService
from banking_api.domain.enums import (
    ApprovalStatus,
    OperationStatus,
    PolicyDecision,
    WorkflowStatus,
)
from banking_api.domain.principal import ExecutionPrincipal, Principal
from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import ApprovalModel, EventModel, OperationModel
from banking_api.policy.service import PolicyResult, PolicyService
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.security.reauthentication.mock_provider import MockReauthenticationProvider
from banking_api.tools.banking import (
    build_commit_transfer_tool,
    build_get_balance_tool,
    build_get_transfer_status_tool,
    build_list_accounts_tool,
    build_search_payees_tool,
)
from banking_api.tools.executor import ToolExecutor
from banking_api.transfers.mock_provider import MockTransferProvider
from banking_api.transfers.provider import (
    TransferProviderFaultMode,
    TransferProviderRequest,
)
from banking_api.workflows.transfer.engine import TransferWorkflowEngine


def operation_runtime(app, *, fault_mode=TransferProviderFaultMode.SUCCESS, policy=None):  # type: ignore[no-untyped-def]
    bank = MockBankService(
        fixture_user_ids=frozenset(
            {
                "dev-user-001",
                "operation-user",
                "expiry-user",
                "balance-user",
                "crash-b-user",
                "approval-expiry-user",
                "created-expiry-user",
                "claim-user",
                "worker-crash-user",
                "unknown-worker-user",
                "unavailable-user",
                "submitted-worker-user",
                "risk-yellow-user",
                "risk-boundary-yellow-user",
                "risk-boundary-red-user",
                "risk-escalation-user",
                "risk-mutation-user",
                "risk-exposure-user",
                "risk-injection-user",
            }
        )
    )
    provider = MockTransferProvider(app.state.test_session_factory, bank, fault_mode=fault_mode)
    registry = ToolRegistry()
    registry.register(build_list_accounts_tool(bank))
    registry.register(build_get_balance_tool(bank, provider.effective_balance))
    registry.register(build_search_payees_tool(bank))
    registry.register(build_commit_transfer_tool(app.state.test_session_factory, provider))
    registry.register(build_get_transfer_status_tool(app.state.test_session_factory, provider))
    engine = TransferWorkflowEngine(ToolExecutor(registry, policy or PolicyService()))
    app.state.transfer_workflow_engine = engine
    return bank, provider, registry, engine


async def authorize_workflow(
    app,
    engine,
    *,
    user_id="operation-user",
    clock=None,
    approval_ttl_seconds=600,
    reauth_ttl_seconds=300,
):  # type: ignore[no-untyped-def]
    bus = app.state.event_bus
    workflow = await create_ready_workflow(app, bus, engine, user_id=user_id)
    authorization_clock = clock or (lambda: datetime.now(UTC))

    def service(session):  # type: ignore[no-untyped-def]
        return WorkflowService(
            session,
            bus,
            engine,
            reauth_provider=MockReauthenticationProvider("operation-test-code"),
            clock=authorization_clock,
            approval_ttl_seconds=approval_ttl_seconds,
            reauth_ttl_seconds=reauth_ttl_seconds,
        )

    async with app.state.test_session_factory() as session:
        approved = await service(session).approve(
            workflow.workflow_id,
            user_id=user_id,
            expected_version=workflow.version,
        )
    async with app.state.test_session_factory() as session:
        challenged = await service(session).start_reauthentication(
            workflow.workflow_id,
            user_id=user_id,
            expected_version=approved.version,
        )
    async with app.state.test_session_factory() as session:
        ready = await service(session).verify_reauthentication(
            workflow.workflow_id,
            user_id=user_id,
            reauth_id=challenged.reauth_summary.reauth_id,  # type: ignore[union-attr]
            verification_code="operation-test-code",
            expected_version=challenged.version,
        )
    return ready


async def test_happy_path_consumes_approval_and_debits_exactly_once(app) -> None:
    bank, provider, registry, engine = operation_runtime(app)
    ready = await authorize_workflow(app, engine)
    starting_balance = Decimal(
        str(bank.get_balance("acc_salary", user_id=ready.user_id)["balance"])
    )

    async with app.state.test_session_factory() as session:
        operation = await OperationService(session, app.state.event_bus, engine).commit_workflow(
            ready.workflow_id,
            user_id=ready.user_id,
            expected_version=ready.version,
        )

    assert operation.status is OperationStatus.SUCCEEDED
    assert await provider.effective_balance(
        ready.user_id, "acc_salary"
    ) == starting_balance - Decimal("2000.00")
    assert await provider.transfer_count() == 1
    async with app.state.test_session_factory() as session:
        persisted = await session.get(OperationModel, operation.operation_id)
        approval = await session.get(
            ApprovalModel,
            ready.approval_summary.approval_id,  # type: ignore[union-attr]
        )
        count = await session.scalar(select(func.count()).select_from(OperationModel))
        operation_events = list(
            (
                await session.execute(
                    select(EventModel).where(EventModel.event_type.like("operation.%"))
                )
            ).scalars()
        )
    assert persisted is not None
    assert persisted.payload_hash == approval.payload_hash  # type: ignore[union-attr]
    assert approval.status is ApprovalStatus.CONSUMED  # type: ignore[union-attr]
    assert approval.consumed_by_operation_id == operation.operation_id  # type: ignore[union-attr]
    assert count == 1
    assert operation_events
    assert all("idempotency_key" not in event.data_json for event in operation_events)
    assert all("payload" not in event.data_json for event in operation_events)
    commit_spec = registry.get("transfer.commit")
    assert commit_spec is not None
    assert commit_spec.side_effect is True
    assert commit_spec.risk_level.value == "R4_FINANCIAL_COMMIT"
    assert commit_spec.allowed_callers == frozenset({"workflow:transfer"})


async def test_timeout_after_accept_is_unknown_then_reconciles_without_resubmit(
    app, client
) -> None:
    _, provider, _, engine = operation_runtime(
        app, fault_mode=TransferProviderFaultMode.TIMEOUT_AFTER_ACCEPT
    )
    ready = await authorize_workflow(app, engine, user_id="dev-user-001")
    committed = await client.post(
        f"/api/v1/workflows/{ready.workflow_id}/actions/commit",
        json={"expected_version": ready.version},
    )
    assert committed.status_code == 200
    committed_workflow = committed.json()
    assert committed_workflow["status"] == "COMMITTING"
    assert committed_workflow["operation_summary"]["status"] == "UNKNOWN"
    operation_id = committed_workflow["operation_summary"]["operation_id"]
    unknown = (await client.get(f"/api/v1/operations/{operation_id}")).json()
    assert unknown["status"] == "UNKNOWN"
    assert await provider.transfer_count() == 1

    # UNKNOWN reconciliation queries status; it must never call submit again.
    async def forbidden_submit(_request):  # type: ignore[no-untyped-def]
        raise AssertionError("UNKNOWN must not be resubmitted")

    provider.submit_transfer = forbidden_submit  # type: ignore[method-assign]
    reconciled = await client.post(
        f"/api/v1/operations/{operation_id}/actions/reconcile",
        json={"expected_version": unknown["version"]},
    )
    assert reconciled.status_code == 200
    assert reconciled.json()["status"] == "SUCCEEDED"
    final_workflow = (await client.get(f"/api/v1/workflows/{ready.workflow_id}")).json()
    assert final_workflow["status"] == "SUCCEEDED"
    assert await provider.transfer_count() == 1


async def test_created_crash_boundaries_resume_same_operation_and_key(app) -> None:
    _, provider, _, engine = operation_runtime(app)
    ready = await authorize_workflow(app, engine)
    async with app.state.test_session_factory() as session:
        created = await OperationService(session, app.state.event_bus, engine).prepare_transfer(
            ready.workflow_id,
            user_id=ready.user_id,
            expected_version=ready.version,
        )
    async with app.state.test_session_factory() as session:
        before = await session.get(OperationModel, created.operation_id)
        key = before.idempotency_key  # type: ignore[union-attr]
    assert created.status is OperationStatus.CREATED

    # Crash A: a fresh service resumes after the local transaction committed.
    async with app.state.test_session_factory() as session:
        result = await OperationService(session, app.state.event_bus, engine).reconcile(
            created.operation_id,
            user_id=ready.user_id,
            expected_version=created.version,
        )
    assert result.status is OperationStatus.SUCCEEDED
    assert await provider.transfer_count() == 1
    async with app.state.test_session_factory() as session:
        after = await session.get(OperationModel, created.operation_id)
    assert after.idempotency_key == key  # type: ignore[union-attr]

    # Crash B is exercised independently: provider applies while local state stays CREATED.
    _, provider2, _, engine2 = operation_runtime(app)
    ready2 = await authorize_workflow(app, engine2, user_id="crash-b-user")
    async with app.state.test_session_factory() as session:
        created2 = await OperationService(session, app.state.event_bus, engine2).prepare_transfer(
            ready2.workflow_id,
            user_id=ready2.user_id,
            expected_version=ready2.version,
        )
        internal = await session.get(OperationModel, created2.operation_id)
        payload = internal.payload_json  # type: ignore[union-attr]
        key2 = internal.idempotency_key  # type: ignore[union-attr]
    await provider2.submit_transfer(
        TransferProviderRequest(
            user_id=ready2.user_id,
            idempotency_key=key2,
            source_account_id=payload["source_account_id"],
            payee_id=payload["payee_id"],
            amount=payload["amount"],
            currency=payload["currency"],
        )
    )
    async with app.state.test_session_factory() as session:
        recovered = await OperationService(session, app.state.event_bus, engine2).reconcile(
            created2.operation_id,
            user_id=ready2.user_id,
            expected_version=created2.version,
        )
    assert recovered.status is OperationStatus.SUCCEEDED
    assert await provider2.transfer_count() == 2  # includes Crash A's distinct transfer


async def test_provider_replay_same_key_debits_once(app) -> None:
    bank, provider, _, _ = operation_runtime(app)
    before = Decimal(str(bank.get_balance("acc_salary", user_id="operation-user")["balance"]))
    request = TransferProviderRequest(
        user_id="operation-user",
        idempotency_key=uuid4(),
        source_account_id="acc_salary",
        payee_id="payee_001",
        amount=Decimal("100.00"),
        currency="CNY",
    )
    results = [await provider.submit_transfer(request) for _ in range(10)]
    assert len({item.provider_reference for item in results}) == 1
    assert await provider.transfer_count() == 1
    assert await provider.effective_balance("operation-user", "acc_salary") == before - Decimal(
        "100.00"
    )


async def test_stale_double_commit_cancel_and_ownership_are_closed(app, client) -> None:
    _, _, _, engine = operation_runtime(app)
    ready = await authorize_workflow(app, engine, user_id="dev-user-001")
    first = await client.post(
        f"/api/v1/workflows/{ready.workflow_id}/actions/commit",
        json={"expected_version": ready.version},
    )
    assert first.status_code == 200
    operation_id = first.json()["operation_summary"]["operation_id"]
    second = await client.post(
        f"/api/v1/workflows/{ready.workflow_id}/actions/commit",
        json={"expected_version": ready.version},
    )
    assert second.status_code == 409
    cancel = await client.post(
        f"/api/v1/workflows/{ready.workflow_id}/actions/cancel",
        json={"expected_version": first.json()["version"]},
    )
    assert cancel.status_code == 422
    operation = (await client.get(f"/api/v1/operations/{operation_id}")).json()
    assert "idempotency_key" not in operation
    assert "payload" not in operation

    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="other-user", issuer="test", subject="other-user"
    )
    try:
        assert (await client.get(f"/api/v1/operations/{operation_id}")).status_code == 404
        denied = await client.post(
            f"/api/v1/operations/{operation_id}/actions/reconcile",
            json={"expected_version": operation["version"]},
        )
        assert denied.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_principal)


class DenyCommitPolicy(PolicyService):
    def evaluate(self, **kwargs):  # type: ignore[no-untyped-def]
        spec = kwargs["spec"]
        if spec is not None and spec.capability_id == "transfer.commit":
            return PolicyResult(decision=PolicyDecision.DENY, reason="test deny")
        return super().evaluate(**kwargs)


async def test_policy_deny_and_fresh_balance_failure_create_nothing(app) -> None:
    _, provider, _, engine = operation_runtime(app, policy=DenyCommitPolicy())
    ready = await authorize_workflow(app, engine)
    async with app.state.test_session_factory() as session:
        with pytest.raises(OperationActionError, match="TRANSFER_COMMIT_POLICY_DENIED"):
            await OperationService(session, app.state.event_bus, engine).prepare_transfer(
                ready.workflow_id,
                user_id=ready.user_id,
                expected_version=ready.version,
            )
    assert await provider.transfer_count() == 0

    _, provider2, _, engine2 = operation_runtime(app)
    ready2 = await authorize_workflow(app, engine2, user_id="balance-user")
    await provider2.submit_transfer(
        TransferProviderRequest(
            user_id="balance-user",
            idempotency_key=uuid4(),
            source_account_id="acc_salary",
            payee_id="payee_001",
            amount=Decimal("23000.00"),
            currency="CNY",
        )
    )
    async with app.state.test_session_factory() as session:
        with pytest.raises(OperationActionError, match="FINAL_TRANSFER_VALIDATION_FAILED"):
            await OperationService(session, app.state.event_bus, engine2).prepare_transfer(
                ready2.workflow_id,
                user_id=ready2.user_id,
                expected_version=ready2.version,
            )
    async with app.state.test_session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(OperationModel)
            .where(OperationModel.workflow_id == ready2.workflow_id)
        )
        approval = await session.get(
            ApprovalModel,
            ready2.approval_summary.approval_id,  # type: ignore[union-attr]
        )
    assert count == 0
    assert approval.status is ApprovalStatus.APPROVED  # type: ignore[union-attr]
    assert approval.consumed_at is None  # type: ignore[union-attr]


async def test_commit_expiry_repairs_workflow_and_created_recovery_ignores_ttl(app) -> None:
    clock = MutableClock()
    _, _, _, engine = operation_runtime(app)
    ready = await authorize_workflow(
        app,
        engine,
        user_id="expiry-user",
        clock=clock,
        approval_ttl_seconds=10,
        reauth_ttl_seconds=5,
    )
    clock.advance(seconds=6)
    async with app.state.test_session_factory() as session:
        with pytest.raises(OperationActionError, match="REAUTH_EXPIRED"):
            await OperationService(
                session, app.state.event_bus, engine, clock=clock
            ).prepare_transfer(
                ready.workflow_id,
                user_id=ready.user_id,
                expected_version=ready.version,
            )
    async with app.state.test_session_factory() as session:
        repaired = await WorkflowService(session, app.state.event_bus, engine).get(
            ready.workflow_id, user_id=ready.user_id
        )
    assert repaired.status is WorkflowStatus.REAUTH_REQUIRED

    approval_clock = MutableClock()
    approval_ready = await authorize_workflow(
        app,
        engine,
        user_id="approval-expiry-user",
        clock=approval_clock,
        approval_ttl_seconds=10,
        reauth_ttl_seconds=30,
    )
    approval_clock.advance(seconds=11)
    async with app.state.test_session_factory() as session:
        with pytest.raises(OperationActionError, match="APPROVAL_EXPIRED"):
            await OperationService(
                session, app.state.event_bus, engine, clock=approval_clock
            ).prepare_transfer(
                approval_ready.workflow_id,
                user_id=approval_ready.user_id,
                expected_version=approval_ready.version,
            )
    async with app.state.test_session_factory() as session:
        approval_repaired = await WorkflowService(session, app.state.event_bus, engine).get(
            approval_ready.workflow_id, user_id=approval_ready.user_id
        )
        operation_count = await session.scalar(
            select(func.count())
            .select_from(OperationModel)
            .where(OperationModel.workflow_id == approval_ready.workflow_id)
        )
    assert approval_repaired.status is WorkflowStatus.READY_FOR_REVIEW
    assert approval_repaired.approval_summary.status is ApprovalStatus.EXPIRED  # type: ignore[union-attr]
    assert approval_repaired.reauth_summary.status.value == "INVALIDATED"  # type: ignore[union-attr]
    assert operation_count == 0

    clock2 = MutableClock()
    ready2 = await authorize_workflow(
        app,
        engine,
        user_id="created-expiry-user",
        clock=clock2,
        approval_ttl_seconds=10,
        reauth_ttl_seconds=5,
    )
    async with app.state.test_session_factory() as session:
        created = await OperationService(
            session, app.state.event_bus, engine, clock=clock2
        ).prepare_transfer(
            ready2.workflow_id,
            user_id=ready2.user_id,
            expected_version=ready2.version,
        )
    clock2.advance(seconds=30)
    async with app.state.test_session_factory() as session:
        recovered = await OperationService(
            session, app.state.event_bus, engine, clock=clock2
        ).reconcile(
            created.operation_id,
            user_id=ready2.user_id,
            expected_version=created.version,
        )
    assert recovered.status is OperationStatus.SUCCEEDED


async def test_definitive_provider_failure_never_debits(app) -> None:
    _, provider, _, engine = operation_runtime(
        app, fault_mode=TransferProviderFaultMode.DEFINITIVE_FAILURE
    )
    ready = await authorize_workflow(app, engine)
    before = await provider.effective_balance(ready.user_id, "acc_salary")
    async with app.state.test_session_factory() as session:
        failed = await OperationService(session, app.state.event_bus, engine).commit_workflow(
            ready.workflow_id,
            user_id=ready.user_id,
            expected_version=ready.version,
        )
    assert failed.status is OperationStatus.FAILED
    assert await provider.effective_balance(ready.user_id, "acc_salary") == before
    assert await provider.transfer_count() == 1


async def test_reconcile_requires_current_operation_version(app) -> None:
    _, _, _, engine = operation_runtime(app)
    ready = await authorize_workflow(app, engine)
    async with app.state.test_session_factory() as session:
        created = await OperationService(session, app.state.event_bus, engine).prepare_transfer(
            ready.workflow_id,
            user_id=ready.user_id,
            expected_version=ready.version,
        )
    async with app.state.test_session_factory() as session:
        with pytest.raises(OperationVersionConflictError):
            await OperationService(session, app.state.event_bus, engine).reconcile(
                created.operation_id,
                user_id=ready.user_id,
                expected_version=created.version + 1,
            )
    async with app.state.test_session_factory() as session:
        with pytest.raises(WorkflowActionError):
            await WorkflowService(session, app.state.event_bus, engine).cancel(
                ready.workflow_id,
                user_id=ready.user_id,
                expected_version=ready.version + 1,
            )


async def test_agents_cannot_invoke_transfer_commit_even_with_injected_prompt(app) -> None:
    _, provider, registry, _ = operation_runtime(app)
    executor = ToolExecutor(registry, PolicyService())
    for caller, allowlist in (
        ("agent:minimal-banking", frozenset({"account.list", "account.get_balance"})),
        (
            "agent:financial-analysis",
            frozenset(
                {
                    "account.list",
                    "transaction.spending_summary",
                    "transaction.category_breakdown",
                    "transaction.compare_periods",
                    "transaction.top_transactions",
                }
            ),
        ),
        ("skill:monthly-spending-report", frozenset()),
    ):
        result = await executor.execute(
            tool_name="commit_transfer",
            arguments={"operation_id": str(uuid4())},
            caller=caller,
            principal=ExecutionPrincipal.for_workflow("dev-user-001"),
            agent_allowlist=allowlist,
        )
        assert result.ok is False
        assert result.error.code.value == "TOOL_NOT_ALLOWED"  # type: ignore[union-attr]
    assert await provider.transfer_count() == 0
