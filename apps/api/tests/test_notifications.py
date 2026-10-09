# ruff: noqa: F811
from datetime import UTC, timedelta
from uuid import UUID

from sqlalchemy import select
from test_recurring_transfers import recurring
from test_scheduled_transfers import create_schedule, schedule_enabled  # noqa: F401
from test_transfer_operations import operation_runtime

from banking_api.application.notification_service import notify_schedule_result
from banking_api.application.schedule_service import ScheduleService
from banking_api.persistence.models import NotificationModel, ScheduledTransferModel, WorkflowModel
from banking_api.runtime.schedule_worker import ScheduleWorker


async def test_inbox_owner_read_delete_and_deleted_result_not_recreated(app, client):
    async with app.state.test_session_factory() as session:
        first = NotificationModel(
            user_id="dev-user-001", source_key="test:one", title="预约转账执行成功", message="成功"
        )
        other = NotificationModel(
            user_id="someone-else", source_key="test:other", title="私密消息", message="私密"
        )
        session.add_all([first, other])
        await session.commit()
        first_id, other_id = first.notification_id, other.notification_id
    inbox = (await client.get("/api/v1/notifications")).json()
    assert inbox["unread_count"] == 1
    assert [item["notification_id"] for item in inbox["items"]] == [str(first_id)]
    for action in ("read", "delete"):
        response = (
            await client.post(f"/api/v1/notifications/{other_id}/read")
            if action == "read"
            else await client.delete(f"/api/v1/notifications/{other_id}")
        )
        assert response.status_code == 404
    read = await client.post(f"/api/v1/notifications/{first_id}/read")
    assert read.status_code == 200 and read.json()["read_at"]
    again = await client.post(f"/api/v1/notifications/{first_id}/read")
    assert again.json()["read_at"] == read.json()["read_at"]
    assert (await client.get("/api/v1/notifications")).json()["unread_count"] == 0
    assert (await client.delete(f"/api/v1/notifications/{first_id}")).status_code == 204
    assert (await client.get("/api/v1/notifications")).json()["items"] == []


async def test_recurring_each_execution_notifies_once_even_after_delete(app, schedule_enabled):
    _, _, _, engine = operation_runtime(app)
    ready, _, rows = await recurring(app, engine)
    for index, row in enumerate(rows[:2], 1):
        due = row.scheduled_for.replace(tzinfo=UTC) + timedelta(seconds=1)
        worker = ScheduleWorker(
            app.state.test_session_factory, app.state.event_bus, engine, clock=lambda due=due: due
        )
        assert await worker.run_once() == 1
        assert await worker.run_once() == 0
        async with app.state.test_session_factory() as session:
            alerts = (await session.scalars(select(NotificationModel))).all()
            assert len(alerts) == index
            alert = next(n for n in alerts if n.schedule_id == row.schedule_id)
            assert alert.user_id == ready.user_id and alert.read_at is None
            assert f"第 {index} 期" in alert.message and "执行成功" in alert.title
            alert.deleted_at = due
            workflow = await session.get(WorkflowModel, row.workflow_id)
            scheduled = await session.get(ScheduledTransferModel, row.schedule_id)
            await notify_schedule_result(session, scheduled, workflow, "SUCCEEDED", due)
            await session.commit()
            assert len((await session.scalars(select(NotificationModel))).all()) == index


async def test_failed_execution_generates_failure_notification(app, schedule_enabled):
    _, _, _, engine = operation_runtime(app)
    engine.mock_scheduling_supported = True
    ready = await create_schedule(app, engine)
    async with app.state.test_session_factory() as session:
        scheduled = await ScheduleService(session, engine).authorize(
            UUID(ready.state["draft"]["schedule_id"]), ready.user_id, ready.version
        )
    due = scheduled.execute_deadline.replace(tzinfo=UTC) + timedelta(seconds=1)
    worker = ScheduleWorker(
        app.state.test_session_factory, app.state.event_bus, engine, clock=lambda due=due: due
    )
    assert await worker.run_once() == 1
    assert await worker.run_once() == 0
    async with app.state.test_session_factory() as session:
        alerts = (await session.scalars(select(NotificationModel))).all()
        assert len(alerts) == 1 and alerts[0].title == "预约转账已过期未执行"


async def test_unknown_result_not_success_until_recovery_and_no_duplicate(app, schedule_enabled):
    from banking_api.application.operation_service import OperationService
    from banking_api.domain.enums import OperationStatus
    from banking_api.persistence.models import OperationModel
    from banking_api.transfers.provider import TransferProviderFaultMode

    _, provider, _, engine = operation_runtime(
        app, fault_mode=TransferProviderFaultMode.TIMEOUT_AFTER_ACCEPT
    )
    engine.mock_scheduling_supported = True
    ready = await create_schedule(app, engine)
    async with app.state.test_session_factory() as session:
        scheduled = await ScheduleService(session, engine).authorize(
            UUID(ready.state["draft"]["schedule_id"]), ready.user_id, ready.version
        )
    due = scheduled.scheduled_for.replace(tzinfo=UTC) + timedelta(seconds=1)
    await ScheduleWorker(
        app.state.test_session_factory, app.state.event_bus, engine, clock=lambda: due
    ).run_once()
    async with app.state.test_session_factory() as session:
        row = await session.get(ScheduledTransferModel, scheduled.schedule_id)
        operation = await session.get(OperationModel, row.operation_id)
        assert operation.status is OperationStatus.UNKNOWN
        assert (await session.scalars(select(NotificationModel))).all() == []
        final = await OperationService(
            session, app.state.event_bus, engine, clock=lambda: due + timedelta(seconds=10)
        ).reconcile(
            operation.operation_id, user_id=ready.user_id, expected_version=operation.version
        )
        assert final.status is OperationStatus.SUCCEEDED
        again = await OperationService(session, app.state.event_bus, engine).reconcile(
            final.operation_id, user_id=ready.user_id, expected_version=final.version
        )
        assert again.status is OperationStatus.SUCCEEDED
        assert len((await session.scalars(select(NotificationModel))).all()) == 1
    assert await provider.transfer_count() == 1
