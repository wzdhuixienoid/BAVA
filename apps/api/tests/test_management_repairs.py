import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from banking_test_helpers import authenticate_workflow
from sqlalchemy import func, select
from test_subscriptions import build_runtime
from test_transfer_operations import operation_runtime

from banking_api.api.dependencies import get_current_principal
from banking_api.application.conversation_service import ConversationService
from banking_api.application.operation_service import OperationActionError, OperationService
from banking_api.application.workflow_service import WorkflowService
from banking_api.domain.enums import OperationStatus, TaskStatus, WorkflowStatus
from banking_api.domain.principal import ExecutionPrincipal, Principal
from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import (
    ConversationModel,
    MockBankTransferModel,
    MockSubscriptionActionModel,
    MockSubscriptionCancellationModel,
    MockSubscriptionStateModel,
    TaskModel,
)
from banking_api.subscriptions.answers import SUBSCRIPTION_OVERVIEW_HINT, subscription_answer
from banking_api.subscriptions.contracts import next_billing
from banking_api.subscriptions.provider import (
    MockSubscriptionProvider,
    SubscriptionCancellationRequest,
    SubscriptionProviderFaultMode,
)
from banking_api.subscriptions.service import SubscriptionAnalysisService
from banking_api.tools.banking.search_payees import build_list_payees_tool
from banking_api.workflows.subscription_cancel.models import SubscriptionCancelIntent
from banking_api.workflows.transfer.models import TransferIntent
from banking_api.workflows.transfer.risk import TransferRiskPolicy


@pytest.mark.parametrize("amount", ["0.01", "1.00", "500.00", "1000.00", "1000.01", "20000.00"])
def test_every_outflow_requires_confirmation_and_reauthentication(amount):
    risk = TransferRiskPolicy().evaluate(
        requested_amount=Decimal(amount),
        currency="CNY",
        business_date=datetime.now(UTC).date(),
        successful_transfer_total_today=Decimal("0"),
        in_flight_transfer_exposure_today=Decimal("0"),
        evaluated_at=datetime.now(UTC),
    )
    assert risk.level.value == "RED"
    assert risk.required_approval and risk.required_reauthentication


async def test_delete_is_idempotent_and_preserves_records(app, client):
    created = (await client.post("/api/v1/conversations", json={"title": "可删除"})).json()
    cid = created["conversation_id"]
    accepted = (
        await client.post(f"/api/v1/conversations/{cid}/messages", json={"content": "你好"})
    ).json()
    assert (await client.delete(f"/api/v1/conversations/{cid}")).status_code == 409
    await app.state.task_runner.run(UUID(accepted["task_id"]))
    assert (await client.delete(f"/api/v1/conversations/{cid}")).status_code == 204
    assert (await client.delete(f"/api/v1/conversations/{cid}")).status_code == 204
    assert (await client.get(f"/api/v1/conversations/{cid}")).status_code == 404
    assert (
        await client.post(f"/api/v1/conversations/{cid}/messages", json={"content": "再说一句"})
    ).status_code == 404
    assert (await client.get("/api/v1/conversations")).json() == []
    async with app.state.test_session_factory() as session:
        assert (await session.get(ConversationModel, UUID(cid))).deleted_at is not None
        assert (
            await session.get(TaskModel, UUID(accepted["task_id"]))
        ).status is TaskStatus.COMPLETED
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="another", issuer="test", subject="another"
    )
    assert (await client.delete(f"/api/v1/conversations/{cid}")).status_code == 404


async def test_payee_confirmation_persistence_isolation_and_transfer(app, client):
    body = {
        "display_name": "新朋友",
        "bank_name": "星河银行（虚构）",
        "account_suffix": "6789",
        "confirmed": False,
    }
    assert (await client.post("/api/v1/payees", json=body)).status_code == 409
    body["confirmed"] = True
    first = (await client.post("/api/v1/payees", json=body)).json()
    assert first["masked_account"] == "****6789"
    assert (await client.post("/api/v1/payees", json=body)).json()["payee_id"] == first["payee_id"]
    assert len((await client.get("/api/v1/payees?query=新朋友")).json()) == 1
    _, _, registry, engine = operation_runtime(app)
    bank = MockBankService()
    tool = build_list_payees_tool(bank, app.state.test_session_factory)
    output = await tool.handler(
        type("Context", (), {"principal": ExecutionPrincipal.for_task("dev-user-001")})(),
        tool.input_model(),
    )
    assert any(row.payee_id == first["payee_id"] for row in output.payees)
    async with app.state.test_session_factory() as session:
        service = ConversationService(session, app.state.event_bus)
        conv = await service.create(user_id="dev-user-001", title="新收款人转账")
        task = await service.accept_message(
            conversation_id=conv.conversation_id, user_id=conv.user_id, content="给新朋友转1元"
        )
    async with app.state.test_session_factory() as session:
        workflow = await WorkflowService(session, app.state.event_bus, engine).create_transfer(
            user_id=conv.user_id,
            conversation_id=conv.conversation_id,
            source_task_id=task.task_id,
            intent=TransferIntent(
                recipient_query="新朋友", amount="1.00", source_account_hint="工资卡"
            ),
        )
        assert workflow.state["review_payload"]["payee_id"] == first["payee_id"]
        approved = await WorkflowService(session, app.state.event_bus, engine).approve(
            workflow.workflow_id, user_id=conv.user_id, expected_version=workflow.version
        )
    ready = await authenticate_workflow(app, engine, approved)
    async with app.state.test_session_factory() as session:
        operation = await OperationService(session, app.state.event_bus, engine).commit_workflow(
            ready.workflow_id, user_id=ready.user_id, expected_version=ready.version
        )
        assert operation.status is OperationStatus.SUCCEEDED
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="another", issuer="test", subject="another"
    )
    assert (await client.get("/api/v1/payees")).json() == []


async def new_subscription_workflow(app, runtime, *, resume=False):
    _, _, engine, subscriptions, _, _ = runtime
    async with app.state.test_session_factory() as session:
        service = ConversationService(session, app.state.event_bus)
        conv = await service.create(user_id="dev-user-001", title="订阅管理")
        task = await service.accept_message(
            conversation_id=conv.conversation_id,
            user_id=conv.user_id,
            content="恢复星幕视频" if resume else "取消星幕视频",
        )
    async with app.state.test_session_factory() as session:
        return await WorkflowService(
            session, app.state.event_bus, engine, subscription_engine=subscriptions
        ).create_subscription_cancel(
            user_id=conv.user_id,
            conversation_id=conv.conversation_id,
            source_task_id=task.task_id,
            intent=SubscriptionCancelIntent(subscription_query="星幕视频"),
            resume=resume,
        )


async def commit_subscription(app, runtime, workflow):
    _, _, engine, subscriptions, _, _ = runtime
    async with app.state.test_session_factory() as session:
        approved = await WorkflowService(
            session, app.state.event_bus, engine, subscription_engine=subscriptions
        ).approve(workflow.workflow_id, user_id=workflow.user_id, expected_version=workflow.version)
    ready = await authenticate_workflow(app, engine, approved, subscription_engine=subscriptions)
    async with app.state.test_session_factory() as session:
        return await OperationService(
            session, app.state.event_bus, engine, subscription_engine=subscriptions
        ).commit_workflow(ready.workflow_id, user_id=ready.user_id, expected_version=ready.version)


async def test_cancel_resume_cancel_is_persistent_without_immediate_charge(app):
    runtime = await build_runtime(app)
    bank, _, engine, subscriptions, _, _ = runtime
    first = await new_subscription_workflow(app, runtime)
    assert (await commit_subscription(app, runtime, first)).status is OperationStatus.SUCCEEDED
    workflow = await new_subscription_workflow(app, runtime, resume=True)
    assert workflow.risk_level.value == "RED" and workflow.presentation.reauthentication_required
    async with app.state.test_session_factory() as session:
        approved = await WorkflowService(
            session, app.state.event_bus, engine, subscription_engine=subscriptions
        ).approve(workflow.workflow_id, user_id=workflow.user_id, expected_version=workflow.version)
        assert approved.status is WorkflowStatus.REAUTH_REQUIRED
        with pytest.raises(OperationActionError, match="WORKFLOW_NOT_READY_FOR_COMMIT"):
            await OperationService(
                session, app.state.event_bus, engine, subscription_engine=subscriptions
            ).prepare_subscription_cancel(
                approved.workflow_id, user_id=approved.user_id, expected_version=approved.version
            )
    ready = await authenticate_workflow(app, engine, approved, subscription_engine=subscriptions)
    async with app.state.test_session_factory() as session:
        service = OperationService(
            session, app.state.event_bus, engine, subscription_engine=subscriptions
        )
        operation = await service.commit_workflow(
            ready.workflow_id, user_id=ready.user_id, expected_version=ready.version
        )
        assert operation.status is OperationStatus.SUCCEEDED
        replay = await service.commit_workflow(
            ready.workflow_id, user_id=ready.user_id, expected_version=ready.version
        )
        assert replay.operation_id == operation.operation_id
        restored = await SubscriptionAnalysisService(bank, session).get(
            "sub_video", user_id=ready.user_id
        )
        assert restored.status.value == "ACTIVE" and restored.cancellable and not restored.resumable
        assert restored.monthly_cost == Decimal("28.00") and restored.next_billing_at is not None
        assert await session.scalar(select(func.count()).select_from(MockBankTransferModel)) == 0
        assert (
            await session.scalar(select(func.count()).select_from(MockSubscriptionActionModel)) == 2
        )
    again = await new_subscription_workflow(app, runtime)
    assert (await commit_subscription(app, runtime, again)).status is OperationStatus.SUCCEEDED
    async with app.state.test_session_factory() as session:
        assert (
            await SubscriptionAnalysisService(bank, session).get("sub_video", user_id=ready.user_id)
        ).status.value == "CANCELLED"
        assert (
            await session.scalar(select(func.count()).select_from(MockSubscriptionActionModel)) == 3
        )


async def test_resume_timeout_reconciles_without_duplicate_action(app):
    runtime = await build_runtime(app)
    _, provider, engine, subscriptions, _, _ = runtime
    await commit_subscription(app, runtime, await new_subscription_workflow(app, runtime))
    provider.fault_mode = SubscriptionProviderFaultMode.TIMEOUT_AFTER_ACCEPT
    operation = await commit_subscription(
        app, runtime, await new_subscription_workflow(app, runtime, resume=True)
    )
    assert operation.status is OperationStatus.UNKNOWN
    async with app.state.test_session_factory() as session:
        recovered = await OperationService(
            session, app.state.event_bus, engine, subscription_engine=subscriptions
        ).reconcile(
            operation.operation_id, user_id="dev-user-001", expected_version=operation.version
        )
        assert recovered.status is OperationStatus.SUCCEEDED
        assert (
            await session.scalar(select(func.count()).select_from(MockSubscriptionActionModel)) == 2
        )


async def test_subscription_version_fences_concurrent_resumes(app):
    provider = MockSubscriptionProvider(app.state.test_session_factory, MockBankService())
    requests = [
        SubscriptionCancellationRequest(
            user_id="dev-user-001",
            subscription_id="sub_fitness",
            idempotency_key=uuid4(),
            expected_version=0,
        )
        for _ in range(2)
    ]
    results = await asyncio.gather(*(provider.resume(request) for request in requests))
    assert sorted(result.outcome for result in results) == ["ACCEPTED", "FAILED"]
    assert any(result.error_code == "SUBSCRIPTION_VERSION_CONFLICT" for result in results)


async def test_legacy_cancellation_can_be_restored_without_erasing_evidence(app):
    key = uuid4()
    async with app.state.test_session_factory() as session:
        session.add(
            MockSubscriptionCancellationModel(
                provider_reference="legacy",
                user_id="dev-user-001",
                subscription_id="sub_video",
                idempotency_key=key,
                status="SUCCEEDED",
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()
    provider = MockSubscriptionProvider(app.state.test_session_factory, MockBankService())
    assert (
        await provider.resume(
            SubscriptionCancellationRequest(
                user_id="dev-user-001",
                subscription_id="sub_video",
                idempotency_key=uuid4(),
                expected_version=0,
            )
        )
    ).outcome == "ACCEPTED"
    async with app.state.test_session_factory() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(MockSubscriptionCancellationModel)
            )
            == 1
        )
        assert (
            await session.get(MockSubscriptionStateModel, ("dev-user-001", "sub_video"))
        ).status == "ACTIVE"


def test_billing_calendar_and_single_overview_hint():
    assert next_billing(
        {"billing_interval": "MONTHLY", "next_billing_at": "2026-01-31T12:00:00Z"},
        datetime(2026, 2, 1, tzinfo=UTC),
    ) == datetime(2026, 2, 28, 12, tzinfo=UTC)
    assert next_billing(
        {"billing_interval": "ANNUAL", "next_billing_at": "2024-02-29T12:00:00Z"},
        datetime(2025, 1, 1, tzinfo=UTC),
    ) == datetime(2025, 2, 28, 12, tzinfo=UTC)
    assert (
        subscription_answer(subscription_answer("查询结果")).count(SUBSCRIPTION_OVERVIEW_HINT) == 1
    )


async def test_resume_failed_and_expired_verification_cannot_create_operation(app):
    from datetime import timedelta

    from banking_api.application.workflow_service import WorkflowActionError
    from banking_api.config.settings import get_settings
    from banking_api.persistence.models import OperationModel, ReauthenticationModel

    runtime = await build_runtime(app)
    _, _, engine, subscriptions, _, _ = runtime
    await commit_subscription(app, runtime, await new_subscription_workflow(app, runtime))
    workflow = await new_subscription_workflow(app, runtime, resume=True)
    async with app.state.test_session_factory() as session:
        service = WorkflowService(
            session, app.state.event_bus, engine, subscription_engine=subscriptions
        )
        approved = await service.approve(
            workflow.workflow_id, user_id=workflow.user_id, expected_version=workflow.version
        )
        challenged = await service.start_reauthentication(
            approved.workflow_id, user_id=approved.user_id, expected_version=approved.version
        )
        with pytest.raises(WorkflowActionError, match="REAUTH_FAILED"):
            await service.verify_reauthentication(
                challenged.workflow_id,
                user_id=challenged.user_id,
                expected_version=challenged.version,
                reauth_id=challenged.reauth_summary.reauth_id,
                verification_code="incorrect-fixture-code",
            )
    async with app.state.test_session_factory() as session:
        service = WorkflowService(
            session, app.state.event_bus, engine, subscription_engine=subscriptions
        )
        current = await service.get(workflow.workflow_id, user_id=workflow.user_id)
        ready = await service.verify_reauthentication(
            current.workflow_id,
            user_id=current.user_id,
            expected_version=current.version,
            reauth_id=current.reauth_summary.reauth_id,
            verification_code=get_settings().mock_reauth_code,
        )
        reauth = await session.get(ReauthenticationModel, ready.reauth_summary.reauth_id)
        reauth.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    async with app.state.test_session_factory() as session:
        with pytest.raises(OperationActionError, match="REAUTH_EXPIRED"):
            await OperationService(
                session, app.state.event_bus, engine, subscription_engine=subscriptions
            ).prepare_subscription_cancel(
                ready.workflow_id, user_id=ready.user_id, expected_version=ready.version
            )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OperationModel)
                .where(OperationModel.workflow_id == ready.workflow_id)
            )
            == 0
        )


async def test_resume_price_change_invalidates_confirmation_and_verification(app):
    from banking_api.persistence.models import OperationModel

    runtime = await build_runtime(app)
    bank, _, engine, subscriptions, _, _ = runtime
    await commit_subscription(app, runtime, await new_subscription_workflow(app, runtime))
    workflow = await new_subscription_workflow(app, runtime, resume=True)
    async with app.state.test_session_factory() as session:
        approved = await WorkflowService(
            session, app.state.event_bus, engine, subscription_engine=subscriptions
        ).approve(workflow.workflow_id, user_id=workflow.user_id, expected_version=workflow.version)
    ready = await authenticate_workflow(app, engine, approved, subscription_engine=subscriptions)
    next(item for item in bank._subscriptions if item["subscription_id"] == "sub_video")[
        "amount"
    ] = "29.00"
    async with app.state.test_session_factory() as session:
        with pytest.raises(OperationActionError, match="APPROVAL_PAYLOAD_MISMATCH"):
            await OperationService(
                session, app.state.event_bus, engine, subscription_engine=subscriptions
            ).prepare_subscription_cancel(
                ready.workflow_id, user_id=ready.user_id, expected_version=ready.version
            )
        current = await WorkflowService(
            session, app.state.event_bus, engine, subscription_engine=subscriptions
        ).get(ready.workflow_id, user_id=ready.user_id)
        assert (
            current.status is WorkflowStatus.READY_FOR_REVIEW
            and current.state["authorization"] is None
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OperationModel)
                .where(OperationModel.workflow_id == ready.workflow_id)
            )
            == 0
        )


async def test_legacy_draft_projects_red_without_rewriting_stored_risk(app):
    from banking_test_helpers import legacy_yellow_authorization
    from test_transfer_authorization import create_ready_workflow

    from banking_api.persistence.models import WorkflowModel

    _, _, _, engine = operation_runtime(app)
    draft = await create_ready_workflow(
        app, app.state.event_bus, engine, user_id="dev-user-001", amount=Decimal("1.00")
    )
    async with app.state.test_session_factory() as session:
        approved = await WorkflowService(session, app.state.event_bus, engine).approve(
            draft.workflow_id, user_id=draft.user_id, expected_version=draft.version
        )
    current = await legacy_yellow_authorization(app, engine, approved)
    assert current.risk_level.value == "RED" and current.presentation.reauthentication_required
    async with app.state.test_session_factory() as session:
        stored = await session.get(WorkflowModel, current.workflow_id)
        assert stored.state_json["risk_decision"]["level"] == "YELLOW"
        stored.status = WorkflowStatus.SUCCEEDED
        await session.commit()
        historical = await WorkflowService(session, app.state.event_bus, engine).get(
            current.workflow_id, user_id=current.user_id
        )
        assert historical.risk_level.value == "YELLOW"
