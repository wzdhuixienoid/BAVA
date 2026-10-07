import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from test_transfer_workflow import build_transfer_runtime, create_transfer_task

from banking_api.application.conversation_service import ConversationService
from banking_api.application.workflow_service import WorkflowActionError, WorkflowService
from banking_api.config.settings import get_settings
from banking_api.domain.enums import ApprovalStatus, ReauthenticationStatus
from banking_api.llm.models import LLMResponse
from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import (
    ApprovalModel,
    EventModel,
    ReauthenticationModel,
    TaskModel,
)
from banking_api.policy.service import PolicyService
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.runtime.event_bus import EventBus
from banking_api.security.guard import SecurityWriteLockedError
from banking_api.security.reauthentication.mock_provider import MockReauthenticationProvider
from banking_api.tools.banking import (
    build_get_balance_tool,
    build_list_accounts_tool,
    build_search_payees_tool,
)
from banking_api.tools.executor import ToolExecutor
from banking_api.workflows.transfer.authorization import (
    canonical_transfer_json,
    canonicalize_transfer_payload,
    transfer_payload_hash,
)
from banking_api.workflows.transfer.engine import TransferWorkflowEngine
from banking_api.workflows.transfer.models import TransferIntent, TransferReviewPayload


def review_payload(**changes: str) -> TransferReviewPayload:
    values = {
        "source_account_id": "acc_salary",
        "source_account_display_name": "工资卡",
        "source_account_masked_number": "****6688",
        "payee_id": "payee_001",
        "payee_display_name": "张三",
        "payee_bank_name": "星海银行",
        "payee_masked_account": "****1234",
        "amount": "2000.00",
        "currency": "CNY",
    }
    values.update(changes)
    return TransferReviewPayload.model_validate(values)


def test_transfer_payload_canonicalization_and_hash_stability() -> None:
    first = review_payload()
    presentation_changed = review_payload(
        source_account_display_name="新的展示名",
        payee_display_name="展示名变化",
        payee_bank_name="新的银行展示名",
    )
    assert canonicalize_transfer_payload(first) == {
        "amount": "2000.00",
        "currency": "CNY",
        "payee_id": "payee_001",
        "source_account_id": "acc_salary",
    }
    assert canonical_transfer_json(first) == (
        '{"amount":"2000.00","currency":"CNY","payee_id":"payee_001",'
        '"source_account_id":"acc_salary"}'
    )
    assert transfer_payload_hash(first) == transfer_payload_hash(presentation_changed)
    assert transfer_payload_hash(first) == transfer_payload_hash(review_payload(amount="2000.0"))
    for mutation in (
        {"amount": "2000.01"},
        {"currency": "USD"},
        {"payee_id": "payee_002"},
        {"source_account_id": "acc_savings"},
    ):
        assert transfer_payload_hash(first) != transfer_payload_hash(review_payload(**mutation))


async def test_fake_e2e_authorization_mutation_and_zero_money_movement(app, client) -> None:
    runner, bank, registry, provider = build_transfer_runtime(
        app,
        [
            LLMResponse(
                content=(
                    '{"route":"TRANSFER_WORKFLOW","requested_output":"WORKFLOW","confidence":0.99}'
                )
            ),
            LLMResponse(
                content=(
                    '{"recipient_query":"张三","amount":"2000.00",'
                    '"currency":null,"source_account_hint":null}'
                )
            ),
        ],
    )
    balances_before = {
        item["account_id"]: bank.get_balance(item["account_id"], user_id="dev-user-001")["balance"]
        for item in bank.list_accounts(user_id="dev-user-001")
    }
    transactions_before = bank.list_transactions(user_id="dev-user-001")
    _, accepted = await create_transfer_task(app, runner)
    async with app.state.test_session_factory() as session:
        task = await session.get(TaskModel, accepted.task_id)
        assert task is not None
        workflow_id = task.output_json["workflow_id"]

    workflow = (await client.get(f"/api/v1/workflows/{workflow_id}")).json()
    workflow = (
        await client.post(
            f"/api/v1/workflows/{workflow_id}/actions/select-payee",
            json={"payee_id": "payee_001", "expected_version": workflow["version"]},
        )
    ).json()
    workflow = (
        await client.post(
            f"/api/v1/workflows/{workflow_id}/actions/select-source-account",
            json={"account_id": "acc_salary", "expected_version": workflow["version"]},
        )
    ).json()
    assert workflow["status"] == "READY_FOR_REVIEW"

    chat_confirmation = await client.post(
        f"/api/v1/conversations/{workflow['conversation_id']}/messages",
        json={"content": "确认，就这个"},
    )
    assert chat_confirmation.status_code == 202
    unchanged = (await client.get(f"/api/v1/workflows/{workflow_id}")).json()
    assert unchanged["status"] == "READY_FOR_REVIEW"
    assert unchanged["approval_summary"] is None

    approved = (
        await client.post(
            f"/api/v1/workflows/{workflow_id}/actions/approve",
            json={"expected_version": unchanged["version"]},
        )
    ).json()
    assert approved["status"] == "REAUTH_REQUIRED"
    assert approved["approval_summary"]["status"] == "APPROVED"
    assert "payload_json" not in approved["approval_summary"]

    stale = await client.post(
        f"/api/v1/workflows/{workflow_id}/actions/start-reauth",
        json={"expected_version": unchanged["version"]},
    )
    assert stale.status_code == 409
    challenged = (
        await client.post(
            f"/api/v1/workflows/{workflow_id}/actions/start-reauth",
            json={"expected_version": approved["version"]},
        )
    ).json()
    assert challenged["reauth_summary"]["status"] == "PENDING"
    assert set(challenged["reauth_summary"]) == {
        "reauth_id",
        "status",
        "method",
        "expires_at",
    }
    ready = (
        await client.post(
            f"/api/v1/workflows/{workflow_id}/actions/verify-reauth",
            json={
                "reauth_id": challenged["reauth_summary"]["reauth_id"],
                "verification_code": get_settings().mock_reauth_code,
                "expected_version": challenged["version"],
            },
        )
    ).json()
    assert ready["status"] == "READY_FOR_COMMIT"
    assert ready["approval_summary"]["status"] == "APPROVED"
    assert ready["reauth_summary"]["status"] == "VERIFIED"

    old_approval_id = ready["approval_summary"]["approval_id"]
    old_reauth_id = ready["reauth_summary"]["reauth_id"]
    old_hash = ready["state"]["authorization"]["approval_payload_hash"]
    mutated_response = await client.post(
        f"/api/v1/workflows/{workflow_id}/actions/set-amount",
        json={"amount": "20000.00", "expected_version": ready["version"]},
    )
    assert mutated_response.status_code == 200
    mutated = mutated_response.json()
    assert mutated["status"] == "READY_FOR_REVIEW"
    assert mutated["state"]["authorization"] is None
    assert mutated["approval_summary"] == {
        "approval_id": old_approval_id,
        "status": "INVALIDATED",
        "expires_at": ready["approval_summary"]["expires_at"],
    }
    assert mutated["reauth_summary"]["reauth_id"] == old_reauth_id
    assert mutated["reauth_summary"]["status"] == "INVALIDATED"
    assert transfer_payload_hash(mutated["state"]["review_payload"]) != old_hash

    serialized = json.dumps(mutated, ensure_ascii=False)
    assert "246810" not in serialized
    assert balances_before == {
        item["account_id"]: bank.get_balance(item["account_id"], user_id="dev-user-001")["balance"]
        for item in bank.list_accounts(user_id="dev-user-001")
    }
    assert bank.list_transactions(user_id="dev-user-001") == transactions_before
    assert len(provider.requests) == 2
    assert not any(
        token in spec.capability_id
        for spec in registry.all()
        for token in ("transfer.commit", "execute_transfer", "payment.submit", "send_money")
    )

    async with app.state.test_session_factory() as session:
        events = list(
            (
                await session.execute(
                    select(EventModel).where(EventModel.task_id == accepted.task_id)
                )
            ).scalars()
        )
        approvals = list((await session.execute(select(ApprovalModel))).scalars())
        reauths = list((await session.execute(select(ReauthenticationModel))).scalars())
    event_payloads = json.dumps([event.data_json for event in events])
    assert "246810" not in event_payloads
    assert all("payload_json" not in event.data_json for event in events)
    assert approvals[0].payload_json == {
        "amount": "2000.00",
        "currency": "CNY",
        "payee_id": "payee_001",
        "source_account_id": "acc_salary",
    }
    assert approvals[0].status is ApprovalStatus.INVALIDATED
    assert approvals[0].consumed_at is None
    assert reauths[0].status is ReauthenticationStatus.INVALIDATED


class MutableClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 25, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, *, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


def transfer_dependencies():  # type: ignore[no-untyped-def]
    bank = MockBankService(fixture_user_ids=frozenset({"authorization-user", "recipient-user"}))
    registry = ToolRegistry()
    registry.register(build_list_accounts_tool(bank))
    registry.register(build_get_balance_tool(bank))
    registry.register(build_search_payees_tool(bank))
    engine = TransferWorkflowEngine(ToolExecutor(registry, PolicyService()))
    return bank, registry, engine


async def create_ready_workflow(
    app,
    bus,
    engine,
    user_id="authorization-user",
    amount=Decimal("2000.00"),
):  # type: ignore[no-untyped-def]
    async with app.state.test_session_factory() as session:
        conversation = await ConversationService(session, bus).create(
            user_id=user_id, title="Authorization test"
        )
    async with app.state.test_session_factory() as session:
        accepted = await ConversationService(session, bus).accept_message(
            conversation_id=conversation.conversation_id,
            user_id=user_id,
            content=f"给张三转{amount}",
        )
    async with app.state.test_session_factory() as session:
        workflow = await WorkflowService(session, bus, engine).create_transfer(
            user_id=user_id,
            conversation_id=conversation.conversation_id,
            source_task_id=accepted.task_id,
            intent=TransferIntent(recipient_query="张三", amount=amount),
        )
    async with app.state.test_session_factory() as session:
        workflow = await WorkflowService(session, bus, engine).select_payee(
            workflow.workflow_id,
            user_id=user_id,
            payee_id="payee_001",
            expected_version=workflow.version,
        )
    async with app.state.test_session_factory() as session:
        workflow = await WorkflowService(session, bus, engine).select_source_account(
            workflow.workflow_id,
            user_id=user_id,
            account_id="acc_salary",
            expected_version=workflow.version,
        )
    return workflow


async def test_injectable_expiry_and_reauthentication_attempt_limits(app) -> None:
    bus = EventBus()
    _, _, engine = transfer_dependencies()
    clock = MutableClock()
    provider = MockReauthenticationProvider("test-only-code")

    def service(session):  # type: ignore[no-untyped-def]
        return WorkflowService(
            session,
            bus,
            engine,
            reauth_provider=provider,
            clock=clock,
            approval_ttl_seconds=10,
            reauth_ttl_seconds=5,
            reauth_max_attempts=3,
        )

    workflow = await create_ready_workflow(app, bus, engine)
    async with app.state.test_session_factory() as session:
        approved = await service(session).approve(
            workflow.workflow_id,
            user_id=workflow.user_id,
            expected_version=workflow.version,
        )
    clock.advance(seconds=11)
    async with app.state.test_session_factory() as session:
        with pytest.raises(WorkflowActionError, match="APPROVAL_EXPIRED"):
            await service(session).start_reauthentication(
                workflow.workflow_id,
                user_id=workflow.user_id,
                expected_version=approved.version,
            )
    async with app.state.test_session_factory() as session:
        expired = await service(session).get(workflow.workflow_id, user_id=workflow.user_id)
    assert expired.status.value == "READY_FOR_REVIEW"
    assert expired.approval_summary.status is ApprovalStatus.EXPIRED  # type: ignore[union-attr]

    async with app.state.test_session_factory() as session:
        approved = await service(session).approve(
            workflow.workflow_id,
            user_id=workflow.user_id,
            expected_version=expired.version,
        )
    async with app.state.test_session_factory() as session:
        challenged = await service(session).start_reauthentication(
            workflow.workflow_id,
            user_id=workflow.user_id,
            expected_version=approved.version,
        )
    clock.advance(seconds=6)
    async with app.state.test_session_factory() as session:
        with pytest.raises(WorkflowActionError, match="REAUTH_EXPIRED"):
            await service(session).verify_reauthentication(
                workflow.workflow_id,
                user_id=workflow.user_id,
                reauth_id=challenged.reauth_summary.reauth_id,  # type: ignore[union-attr]
                verification_code="test-only-code",
                expected_version=challenged.version,
            )
    async with app.state.test_session_factory() as session:
        after_expiry = await service(session).get(workflow.workflow_id, user_id=workflow.user_id)
    assert after_expiry.status.value == "REAUTH_REQUIRED"
    assert after_expiry.reauth_summary.status is ReauthenticationStatus.EXPIRED  # type: ignore[union-attr]

    async with app.state.test_session_factory() as session:
        challenged = await service(session).start_reauthentication(
            workflow.workflow_id,
            user_id=workflow.user_id,
            expected_version=after_expiry.version,
        )
    for attempt in range(3):
        async with app.state.test_session_factory() as session:
            with pytest.raises(WorkflowActionError, match="REAUTH_FAILED"):
                await service(session).verify_reauthentication(
                    workflow.workflow_id,
                    user_id=workflow.user_id,
                    reauth_id=challenged.reauth_summary.reauth_id,  # type: ignore[union-attr]
                    verification_code="wrong",
                    expected_version=challenged.version + attempt,
                )
    async with app.state.test_session_factory() as session:
        failed = await service(session).get(workflow.workflow_id, user_id=workflow.user_id)
    assert failed.reauth_summary.status is ReauthenticationStatus.FAILED  # type: ignore[union-attr]
    assert failed.state["authorization"]["reauth_id"] is None

    async with app.state.test_session_factory() as session:
        with pytest.raises(SecurityWriteLockedError):
            await service(session).start_reauthentication(
                workflow.workflow_id,
                user_id=workflow.user_id,
                expected_version=failed.version,
            )
    clock.advance(seconds=16 * 60)
    async with app.state.test_session_factory() as session:
        with pytest.raises(WorkflowActionError, match="APPROVAL_EXPIRED"):
            await service(session).start_reauthentication(
                workflow.workflow_id,
                user_id=workflow.user_id,
                expected_version=failed.version,
            )
    async with app.state.test_session_factory() as session:
        after_lock = await service(session).get(workflow.workflow_id, user_id=workflow.user_id)
        approved_again = await service(session).approve(
            workflow.workflow_id,
            user_id=workflow.user_id,
            expected_version=after_lock.version,
        )
    async with app.state.test_session_factory() as session:
        challenged_again = await service(session).start_reauthentication(
            workflow.workflow_id,
            user_id=workflow.user_id,
            expected_version=approved_again.version,
        )
    async with app.state.test_session_factory() as session:
        ready = await service(session).verify_reauthentication(
            workflow.workflow_id,
            user_id=workflow.user_id,
            reauth_id=challenged_again.reauth_summary.reauth_id,  # type: ignore[union-attr]
            verification_code="test-only-code",
            expected_version=challenged_again.version,
        )
    assert ready.status.value == "READY_FOR_COMMIT"
    assert ready.reauth_summary.status is ReauthenticationStatus.VERIFIED  # type: ignore[union-attr]


async def test_set_recipient_query_and_cancel_invalidate_authorization(app) -> None:
    bus = EventBus()
    _, _, engine = transfer_dependencies()
    workflow = await create_ready_workflow(app, bus, engine, user_id="recipient-user")
    async with app.state.test_session_factory() as session:
        approved = await WorkflowService(session, bus, engine).approve(
            workflow.workflow_id,
            user_id=workflow.user_id,
            expected_version=workflow.version,
        )
    async with app.state.test_session_factory() as session:
        changed = await WorkflowService(session, bus, engine).set_recipient_query(
            workflow.workflow_id,
            user_id=workflow.user_id,
            recipient_query="李小雨",
            expected_version=approved.version,
        )
    assert changed.status.value == "READY_FOR_REVIEW"
    assert changed.state["draft"]["payee_id"] == "payee_003"
    assert changed.state["review_payload"]["payee_id"] == "payee_003"
    assert changed.approval_summary.status is ApprovalStatus.INVALIDATED  # type: ignore[union-attr]

    async with app.state.test_session_factory() as session:
        approved_again = await WorkflowService(session, bus, engine).approve(
            workflow.workflow_id,
            user_id=workflow.user_id,
            expected_version=changed.version,
        )
    async with app.state.test_session_factory() as session:
        challenged = await WorkflowService(session, bus, engine).start_reauthentication(
            workflow.workflow_id,
            user_id=workflow.user_id,
            expected_version=approved_again.version,
        )
    async with app.state.test_session_factory() as session:
        cancelled = await WorkflowService(session, bus, engine).cancel(
            workflow.workflow_id,
            user_id=workflow.user_id,
            expected_version=challenged.version,
        )
    assert cancelled.status.value == "CANCELLED"
    assert cancelled.approval_summary is not None
    assert cancelled.approval_summary.status is ApprovalStatus.INVALIDATED
    assert cancelled.reauth_summary is not None
    assert cancelled.reauth_summary.status is ReauthenticationStatus.INVALIDATED
