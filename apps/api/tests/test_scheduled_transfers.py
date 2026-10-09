from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from banking_test_helpers import authenticate_workflow
from test_transfer_operations import operation_runtime
from banking_api.application.conversation_service import ConversationService
from banking_api.application.workflow_service import WorkflowService
from banking_api.application.schedule_service import ScheduleService
from banking_api.application.operation_service import OperationService, OperationActionError
from banking_api.config.settings import get_settings
from banking_api.persistence.models import (
    ScheduledTransferModel,
    ScheduledAuthorizationModel,
    ApprovalModel,
    ReauthenticationModel,
    WorkflowModel,
)
from banking_api.runtime.schedule_worker import ScheduleWorker
from banking_api.transfers.schedule_time import parse_execution_time
from banking_api.workflows.transfer.models import TransferIntent


def test_beijing_time_and_ambiguity():
    now = datetime(2026, 10, 8, 5, 0, tzinfo=UTC)
    when, deadline = parse_execution_time("明天上午9点", now)
    assert when == datetime(2026, 10, 9, 1, 0, tzinfo=UTC)
    assert deadline > when
    for value in ["晚上", "下周", "2026-10-07 09:00", "明天上午25点", "2027-01-01 09:00"]:
        with pytest.raises(ValueError):
            parse_execution_time(value, now)


async def create_schedule(app, engine, *, now=None, amount="2", expression="明天上午9点"):
    now = now or datetime.now(UTC)
    async with app.state.test_session_factory() as session:
        conv = await ConversationService(session, app.state.event_bus).create(
            user_id="dev-user-001", title="预约"
        )
        task = await ConversationService(session, app.state.event_bus).accept_message(
            conversation_id=conv.conversation_id, user_id="dev-user-001", content="明天转账"
        )
        service = WorkflowService(session, app.state.event_bus, engine)
        workflow = await service.create_transfer(
            user_id="dev-user-001",
            conversation_id=conv.conversation_id,
            source_task_id=task.task_id,
            intent=TransferIntent(
                recipient_query="李小雨",
                amount=amount,
                source_account_hint="工资卡",
                remark="房租",
                execution_time_text=expression,
            ),
        )
        workflow = await service.approve(
            workflow.workflow_id, user_id=workflow.user_id, expected_version=workflow.version
        )
    return await authenticate_workflow(app, engine, workflow)


@pytest.fixture
def schedule_enabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "mock_scheduled_transfers_enabled", True)


async def test_scope_conversion_expiry_and_worker_once(app, schedule_enabled):
    _, provider, _, engine = operation_runtime(app)
    engine.mock_scheduling_supported = True
    ready = await create_schedule(app, engine)
    schedule_id = ready.state["draft"]["schedule_id"]
    from uuid import UUID

    schedule_id = UUID(schedule_id)
    async with app.state.test_session_factory() as session:
        with pytest.raises(OperationActionError, match="SCOPED_AUTHORIZATION"):
            await OperationService(session, app.state.event_bus, engine).commit_workflow(
                ready.workflow_id, user_id=ready.user_id, expected_version=ready.version
            )
    async with app.state.test_session_factory() as session:
        scheduled = await ScheduleService(session, engine).authorize(
            schedule_id, ready.user_id, ready.version
        )
        assert scheduled.status == "SCHEDULED"
        grant = await session.get(
            ScheduledAuthorizationModel,
            (await session.get(ScheduledTransferModel, schedule_id)).authorization_id,
        )
        assert grant.used_at is None and "verification_code" not in grant.payload_json
    now = scheduled.scheduled_for.replace(tzinfo=UTC) + timedelta(seconds=1)
    worker = ScheduleWorker(
        app.state.test_session_factory, app.state.event_bus, engine, clock=lambda: now
    )
    assert await worker.run_once() == 1
    assert await worker.run_once() == 0
    async with app.state.test_session_factory() as session:
        resource = await ScheduleService(session, engine).get(schedule_id, ready.user_id)
        assert resource.status == "SUCCEEDED"
        grant = await session.get(
            ScheduledAuthorizationModel,
            (await session.get(ScheduledTransferModel, schedule_id)).authorization_id,
        )
        assert grant.used_at is not None
    assert await provider.transfer_count() == 1


@pytest.mark.parametrize("outcome", ["cancel", "expired", "insufficient"])
async def test_cancel_expired_balance_no_debit(app, schedule_enabled, outcome):
    _, provider, _, engine = operation_runtime(app)
    engine.mock_scheduling_supported = True
    ready = await create_schedule(app, engine)
    from uuid import UUID

    schedule_id = UUID(ready.state["draft"]["schedule_id"])
    async with app.state.test_session_factory() as session:
        scheduled = await ScheduleService(session, engine).authorize(
            schedule_id, ready.user_id, ready.version
        )
        if outcome == "cancel":
            scheduled = await ScheduleService(session, engine).cancel(
                schedule_id, ready.user_id, scheduled.version
            )
    now = scheduled.scheduled_for.replace(tzinfo=UTC) + timedelta(
        seconds=1 if outcome != "expired" else 1000
    )
    if outcome == "insufficient":
        # Another transfer spent the unreserved balance before the due appointment.
        from banking_api.transfers.provider import TransferProviderRequest
        from uuid import uuid4

        await provider.submit_transfer(
            TransferProviderRequest(
                user_id=ready.user_id,
                source_account_id="acc_salary",
                payee_id="payee_003",
                amount=Decimal("23864.52"),
                currency="CNY",
                idempotency_key=uuid4(),
            )
        )
    await ScheduleWorker(
        app.state.test_session_factory, app.state.event_bus, engine, clock=lambda: now
    ).run_once()
    async with app.state.test_session_factory() as session:
        row = await ScheduleService(session, engine).get(schedule_id, ready.user_id)
        assert (
            row.status
            == {"cancel": "CANCELLED", "expired": "EXPIRED", "insufficient": "FAILED"}[outcome]
        )
        assert row.operation_id is None
    assert await provider.transfer_count() == (1 if outcome == "insufficient" else 0)


async def test_schedule_target_rebinding_same_suffix_invalidates_authority(app, schedule_enabled):
    from banking_api.persistence.models import PayeeModel
    _,provider,_,engine = operation_runtime(app)
    engine.mock_scheduling_supported = True
    ready = await create_schedule(app,engine)
    from uuid import UUID
    schedule_id = UUID(ready.state["draft"]["schedule_id"])
    async with app.state.test_session_factory() as session:
        resource = await ScheduleService(session,engine).authorize(schedule_id,ready.user_id,ready.version)
        session.add(PayeeModel(payee_id="managed-lixiaoyu",source_payee_id="payee_003",user_id=ready.user_id,
            display_name="李小雨",bank_name="星河银行（虚构）",account_suffix="4815",account_fingerprint="changed-full-account-same-suffix",phone_alias="1003"))
        await session.commit()
    await ScheduleWorker(app.state.test_session_factory,app.state.event_bus,engine,clock=lambda:resource.scheduled_for.replace(tzinfo=UTC)+timedelta(seconds=1)).run_once()
    async with app.state.test_session_factory() as session:
        result=await ScheduleService(session,engine).get(schedule_id,ready.user_id)
        assert result.status == "FAILED" and result.operation_id is None
    assert await provider.transfer_count() == 0


async def test_schedule_list_has_snapshot_task_content(app, schedule_enabled):
    _, _, _, engine = operation_runtime(app)
    engine.mock_scheduling_supported = True
    ready = await create_schedule(app, engine)
    async with app.state.test_session_factory() as session:
        rows = await ScheduleService(session, engine).list(ready.user_id)
        assert len(rows) == 1
        assert rows[0].task_title == "给李小雨转账 ¥2.00"
        assert rows[0].remark == "房租"
        assert rows[0].created_at is not None
        assert await ScheduleService(session, engine).list("other-user") == []


async def test_delete_cancelled_schedule_preserves_evidence_and_owner(app, schedule_enabled):
    from uuid import UUID

    _, _, _, engine = operation_runtime(app)
    engine.mock_scheduling_supported = True
    ready = await create_schedule(app, engine)
    schedule_id = UUID(ready.state["draft"]["schedule_id"])
    async with app.state.test_session_factory() as session:
        service = ScheduleService(session, engine)
        scheduled = await service.get(schedule_id, ready.user_id)
        with pytest.raises(OperationActionError, match="SCHEDULE_NOT_FOUND"):
            await service.delete_cancelled(schedule_id, "other-user", scheduled.version)
        with pytest.raises(OperationActionError, match="ONLY_CANCELLED"):
            await service.delete_cancelled(schedule_id, ready.user_id, scheduled.version)
        cancelled = await service.cancel(schedule_id, ready.user_id, scheduled.version)
        with pytest.raises(OperationActionError, match="VERSION_CONFLICT"):
            await service.delete_cancelled(schedule_id, ready.user_id, scheduled.version)
        await service.delete_cancelled(schedule_id, ready.user_id, cancelled.version)
        assert await service.list(ready.user_id) == []
        assert (await service.get(schedule_id, ready.user_id)).status == "CANCELLED"
        assert await session.get(WorkflowModel, ready.workflow_id) is not None
        assert (await session.get(ScheduledTransferModel, schedule_id)).deleted_at is not None


async def test_delete_chat_keeps_authorized_schedule_executable(app, schedule_enabled):
    from uuid import UUID
    from banking_api.application.conversation_service import ConversationActiveError
    from banking_api.persistence.models import ConversationModel

    _, provider, _, engine = operation_runtime(app)
    engine.mock_scheduling_supported = True
    ready = await create_schedule(app, engine)
    schedule_id = UUID(ready.state["draft"]["schedule_id"])
    async with app.state.test_session_factory() as session:
        service = ScheduleService(session, engine)
        with pytest.raises(ConversationActiveError):
            await ConversationService(session, app.state.event_bus).delete(
                conversation_id=ready.conversation_id, user_id=ready.user_id
            )
        scheduled = await service.authorize(schedule_id, ready.user_id, ready.version)
        await ConversationService(session, app.state.event_bus).delete(
            conversation_id=ready.conversation_id, user_id=ready.user_id
        )
        assert (await session.get(ConversationModel, ready.conversation_id)).deleted_at is not None
        assert (await service.get(schedule_id, ready.user_id)).status == "SCHEDULED"
    due = scheduled.scheduled_for.replace(tzinfo=UTC) + timedelta(seconds=1)
    worker = ScheduleWorker(app.state.test_session_factory, app.state.event_bus, engine, clock=lambda:due)
    assert await worker.run_once() == 1
    assert await provider.transfer_count() == 1


async def test_schedule_creation_requires_current_strong_verification(app, schedule_enabled):
    from uuid import UUID

    _, _, _, engine = operation_runtime(app)
    engine.mock_scheduling_supported = True
    ready = await create_schedule(app, engine)
    schedule_id = UUID(ready.state["draft"]["schedule_id"])
    async with app.state.test_session_factory() as session:
        workflow = await session.get(WorkflowModel, ready.workflow_id)
        reauth_id = UUID(workflow.state_json["authorization"]["reauth_id"])
        evidence = await session.get(ReauthenticationModel, reauth_id)
        evidence.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
        with pytest.raises(OperationActionError, match="STRONG_VERIFICATION_REQUIRED"):
            await ScheduleService(session, engine).authorize(schedule_id, ready.user_id, ready.version)
        assert (await session.get(ScheduledTransferModel, schedule_id)).status == "PENDING_AUTHORIZATION"
