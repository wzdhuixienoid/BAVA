from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from test_subscriptions import create_workflow as create_subscription_workflow
from test_transfer_authorization import create_ready_workflow, transfer_dependencies

from banking_api.application.operation_service import OperationActionError, OperationService
from banking_api.application.workflow_service import WorkflowService
from banking_api.domain.enums import ApprovalStatus
from banking_api.persistence.models import (
    ApprovalModel,
    EventModel,
    OperationModel,
    SecurityGuardStateModel,
)
from banking_api.persistence.repositories.conversations import ConversationRepository
from banking_api.persistence.repositories.tasks import TaskRepository
from banking_api.runtime.event_bus import EventBus
from banking_api.security.guard import (
    SecurityGuardService,
    SecurityGuardStatus,
    SecurityLockReason,
    SecurityWriteLockedError,
)


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


async def context(app):  # type: ignore[no-untyped-def]
    async with app.state.test_session_factory() as session:
        conversation = await ConversationRepository(session).create(
            user_id="dev-user-001", title="security"
        )
        task = await TaskRepository(session).create(
            conversation_id=conversation.conversation_id,
            user_id="dev-user-001",
            task_type="USER_REQUEST",
            input_data={},
        )
        await session.commit()
    return conversation, task


async def record_reauth(app, clock, conversation, task, succeeded):  # type: ignore[no-untyped-def]
    async with app.state.test_session_factory() as session:
        service = SecurityGuardService(session, clock=clock)
        status = await service.record_reauthentication_result(
            user_id="dev-user-001",
            workflow_id=task.task_id,
            conversation_id=conversation.conversation_id,
            task_id=task.task_id,
            succeeded=succeeded,
        )
        await session.commit()
        return status


async def test_two_failures_are_normal_and_third_failure_locks_persistently(app) -> None:
    conversation, task = await context(app)
    clock = Clock(datetime(2026, 9, 28, 10, 0, tzinfo=UTC))

    status = await record_reauth(app, clock, conversation, task, False)
    assert status.status is SecurityGuardStatus.NORMAL
    clock.value += timedelta(minutes=1)
    status = await record_reauth(app, clock, conversation, task, False)
    assert status.status is SecurityGuardStatus.NORMAL
    clock.value += timedelta(minutes=1)
    locked = await record_reauth(app, clock, conversation, task, False)

    assert locked.status is SecurityGuardStatus.WRITE_LOCKED
    assert locked.reason_code is SecurityLockReason.REAUTH_FAILURES
    assert locked.locked_until == clock.value + timedelta(minutes=15)
    async with app.state.test_session_factory() as restarted_session:
        restarted = SecurityGuardService(restarted_session, clock=clock)
        persisted = await restarted.get_status("dev-user-001")
        assert persisted.status is SecurityGuardStatus.WRITE_LOCKED
        with pytest.raises(SecurityWriteLockedError):
            await restarted.require_write_allowed("dev-user-001")
    async with app.state.test_session_factory() as session:
        types = list(
            (
                await session.execute(
                    select(EventModel.event_type).order_by(EventModel.sequence)
                )
            ).scalars()
        )
        assert types.count("security.reauth_failed") == 3
        assert types.count("security.write_lock_activated") == 1


async def test_success_resets_consecutive_reauthentication_failures(app) -> None:
    conversation, task = await context(app)
    clock = Clock(datetime(2026, 9, 28, 10, 0, tzinfo=UTC))

    await record_reauth(app, clock, conversation, task, False)
    await record_reauth(app, clock, conversation, task, False)
    await record_reauth(app, clock, conversation, task, True)
    final = await record_reauth(app, clock, conversation, task, False)

    assert final.status is SecurityGuardStatus.NORMAL
    async with app.state.test_session_factory() as session:
        state = await session.get(SecurityGuardStateModel, "dev-user-001")
        assert state is not None
        assert state.reauth_failure_count == 1


async def test_five_control_bypass_attempts_lock_and_expire_lazily(app) -> None:
    conversation, task = await context(app)
    clock = Clock(datetime(2026, 9, 28, 10, 0, tzinfo=UTC))
    for _ in range(5):
        async with app.state.test_session_factory() as session:
            status = await SecurityGuardService(
                session, clock=clock
            ).record_control_bypass_attempt(
                user_id="dev-user-001",
                workflow_id=task.task_id,
                conversation_id=conversation.conversation_id,
                task_id=task.task_id,
            )
            await session.commit()

    assert status.status is SecurityGuardStatus.WRITE_LOCKED
    assert status.reason_code is SecurityLockReason.CONTROL_BYPASS
    clock.value += timedelta(minutes=14)
    async with app.state.test_session_factory() as session:
        assert (
            await SecurityGuardService(session, clock=clock).get_status("dev-user-001")
        ).status is SecurityGuardStatus.WRITE_LOCKED
    clock.value += timedelta(minutes=2)
    async with app.state.test_session_factory() as session:
        service = SecurityGuardService(session, clock=clock)
        assert (await service.get_status("dev-user-001")).status is SecurityGuardStatus.NORMAL
        await service.require_write_allowed("dev-user-001")
        await session.commit()


async def test_security_status_api_is_principal_scoped(client, app) -> None:
    async with app.state.test_session_factory() as session:
        session.add(
            SecurityGuardStateModel(
                user_id="another-user",
                locked_until=datetime.now(UTC) + timedelta(minutes=15),
                lock_reason=SecurityLockReason.CONTROL_BYPASS.value,
            )
        )
        await session.commit()

    response = await client.get("/api/v1/security/status")

    assert response.status_code == 200
    assert response.json() == {
        "status": "NORMAL",
        "locked_until": None,
        "reason_code": None,
    }


async def test_five_direct_commits_without_controls_activate_lock(app) -> None:
    bus = EventBus()
    _, _, engine = transfer_dependencies()
    workflow = await create_ready_workflow(app, bus, engine)

    for _ in range(4):
        async with app.state.test_session_factory() as session:
            with pytest.raises(OperationActionError, match="WORKFLOW_NOT_READY_FOR_COMMIT"):
                await OperationService(session, bus, engine).prepare_transfer(
                    workflow.workflow_id,
                    user_id=workflow.user_id,
                    expected_version=workflow.version,
                )
    async with app.state.test_session_factory() as session:
        with pytest.raises(SecurityWriteLockedError):
            await OperationService(session, bus, engine).prepare_transfer(
                workflow.workflow_id,
                user_id=workflow.user_id,
                expected_version=workflow.version,
            )
    async with app.state.test_session_factory() as session:
        status = await SecurityGuardService(session).get_status(workflow.user_id)
        operation_count = await session.scalar(select(func.count()).select_from(OperationModel))
    assert status.status is SecurityGuardStatus.WRITE_LOCKED
    assert status.reason_code is SecurityLockReason.CONTROL_BYPASS
    assert operation_count == 0


async def test_write_lock_precedes_transfer_controls_and_preserves_approval(app) -> None:
    bus = EventBus()
    _, _, engine = transfer_dependencies()
    workflow = await create_ready_workflow(app, bus, engine)
    async with app.state.test_session_factory() as session:
        approved = await WorkflowService(session, bus, engine).approve(
            workflow.workflow_id,
            user_id=workflow.user_id,
            expected_version=workflow.version,
        )
    async with app.state.test_session_factory() as session:
        session.add(
            SecurityGuardStateModel(
                user_id=workflow.user_id,
                locked_until=datetime.now(UTC) + timedelta(minutes=15),
                lock_reason=SecurityLockReason.REAUTH_FAILURES.value,
            )
        )
        await session.commit()

    async with app.state.test_session_factory() as session:
        with pytest.raises(SecurityWriteLockedError):
            await OperationService(session, bus, engine).prepare_transfer(
                workflow.workflow_id,
                user_id=workflow.user_id,
                expected_version=approved.version,
            )
    async with app.state.test_session_factory() as session:
        approval = (
            await session.execute(
                select(ApprovalModel).where(ApprovalModel.workflow_id == workflow.workflow_id)
            )
        ).scalar_one()
        operation_count = await session.scalar(
            select(func.count()).select_from(OperationModel).where(
                OperationModel.workflow_id == workflow.workflow_id
            )
        )
    assert approval.status is ApprovalStatus.APPROVED
    assert approval.consumed_at is None
    assert operation_count == 0


async def test_write_lock_blocks_subscription_cancel_without_provider_call(app) -> None:
    runtime, workflow = await create_subscription_workflow(app, "星幕视频")
    _, provider, transfer_engine, subscription_engine, _, _ = runtime
    async with app.state.test_session_factory() as session:
        approved = await WorkflowService(
            session,
            app.state.event_bus,
            transfer_engine,
            subscription_engine=subscription_engine,
        ).approve(
            workflow.workflow_id,
            user_id="dev-user-001",
            expected_version=workflow.version,
        )
    async with app.state.test_session_factory() as session:
        session.add(
            SecurityGuardStateModel(
                user_id="dev-user-001",
                locked_until=datetime.now(UTC) + timedelta(minutes=15),
                lock_reason=SecurityLockReason.CONTROL_BYPASS.value,
            )
        )
        await session.commit()
    async with app.state.test_session_factory() as session:
        with pytest.raises(SecurityWriteLockedError):
            await OperationService(
                session,
                app.state.event_bus,
                transfer_engine,
                subscription_engine=subscription_engine,
            ).prepare_subscription_cancel(
                workflow.workflow_id,
                user_id="dev-user-001",
                expected_version=approved.version,
            )
    assert await provider.cancellation_count() == 0
    async with app.state.test_session_factory() as session:
        approval = (
            await session.execute(
                select(ApprovalModel).where(ApprovalModel.workflow_id == workflow.workflow_id)
            )
        ).scalar_one()
        operation_count = await session.scalar(
            select(func.count()).select_from(OperationModel).where(
                OperationModel.workflow_id == workflow.workflow_id
            )
        )
    assert approval.status is ApprovalStatus.APPROVED
    assert approval.consumed_at is None
    assert operation_count == 0
