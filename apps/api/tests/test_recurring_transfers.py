# ruff: noqa: F811
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from test_scheduled_transfers import (
    create_schedule,
    schedule_enabled,  # noqa: F401
)
from test_transfer_operations import operation_runtime

from banking_api.application.operation_service import OperationActionError
from banking_api.application.schedule_service import ScheduleService
from banking_api.application.workflow_service import WorkflowActionError, WorkflowService
from banking_api.persistence.models import RecurringTransferModel, ScheduledTransferModel
from banking_api.runtime.schedule_worker import ScheduleWorker
from banking_api.transfers.schedule_time import parse_execution_time, parse_monthly_recurrence


def test_early_morning_aliases_and_monthly_dates():
    now = datetime(2026, 10, 8, 5, tzinfo=UTC)
    for period in ["早上", "早晨", "上午"]:
        assert parse_execution_time(f"明天{period}9点", now)[0] == datetime(
            2026, 10, 9, 1, tzinfo=UTC
        )
    rule = parse_monthly_recurrence("每个月1号早上9点，共3次", now)
    assert rule.count == 3
    assert rule.occurrences == [datetime(2026, m, 1, 1, tzinfo=UTC) for m in [11, 12]] + [
        datetime(2027, 1, 1, 1, tzinfo=UTC)
    ]
    rule = parse_monthly_recurrence("每月31号9:00，共3次", datetime(2026, 1, 1, tzinfo=UTC))
    assert [d.month for d in rule.occurrences] == [1, 3, 5]
    for text in [
        "每个月1号",
        "每月1号9点",
        "每月1号晚上，共3次",
        "每月1号9点，共99次",
        "每月32号9点，共3次",
    ]:
        with pytest.raises(ValueError):
            parse_monthly_recurrence(text, now)


async def recurring(app, engine):
    engine.mock_scheduling_supported = True
    ready = await create_schedule(app, engine, expression="每个月1号早上9点，共3次")
    async with app.state.test_session_factory() as session:
        root = await ScheduleService(session, engine).authorize(
            UUID(ready.state["draft"]["schedule_id"]), ready.user_id, ready.version
        )
        rows = list(
            (
                await session.scalars(
                    select(ScheduledTransferModel)
                    .where(ScheduledTransferModel.series_id == root.series_id)
                    .order_by(ScheduledTransferModel.occurrence_index)
                )
            ).all()
        )
    return ready, root, rows


async def test_recurring_once_per_occurrence_and_revocable_scope(app, schedule_enabled):
    _, provider, _, engine = operation_runtime(app)
    ready, root, rows = await recurring(app, engine)
    assert len(rows) == 3 and root.recurrence.count == 3
    assert len({r.workflow_id for r in rows}) == 3
    # First and second occurrence independently enter the original controlled chain.
    for row in rows[:2]:
        due = row.scheduled_for.replace(tzinfo=UTC) + timedelta(seconds=1)
        worker = ScheduleWorker(
            app.state.test_session_factory, app.state.event_bus, engine, clock=lambda due=due: due
        )
        assert await worker.run_once() == 1
        assert await worker.run_once() == 0
        async with app.state.test_session_factory() as session:
            assert (
                await ScheduleService(session, engine).get(row.schedule_id, ready.user_id)
            ).status == "SUCCEEDED"
    assert await provider.transfer_count() == 2
    async with app.state.test_session_factory() as session:
        result = await ScheduleService(session, engine).cancel_series(
            root.schedule_id, ready.user_id, root.series_version
        )
        assert result.series_revoked and result.status == "SUCCEEDED"
        assert (
            await ScheduleService(session, engine).get(rows[2].schedule_id, ready.user_id)
        ).status == "CANCELLED"
    due = rows[2].scheduled_for.replace(tzinfo=UTC) + timedelta(seconds=1)
    assert (
        await ScheduleWorker(
            app.state.test_session_factory, app.state.event_bus, engine, clock=lambda due=due: due
        ).run_once()
        == 0
    )
    assert await provider.transfer_count() == 2


async def test_recurring_cannot_edit_or_reuse_auth_and_is_owner_isolated(app, schedule_enabled):
    _, provider, _, engine = operation_runtime(app)
    ready, root, rows = await recurring(app, engine)
    async with app.state.test_session_factory() as session:
        with pytest.raises(WorkflowActionError, match="RECURRING_SERIES_IMMUTABLE"):
            await WorkflowService(session, app.state.event_bus, engine).set_remark(
                ready.workflow_id,
                user_id=ready.user_id,
                remark="change",
                expected_version=ready.version,
            )
    async with app.state.test_session_factory() as session:
        with pytest.raises(OperationActionError, match="NOT_AUTHORIZABLE"):
            await ScheduleService(session, engine).authorize(
                root.schedule_id, ready.user_id, ready.version
            )
    async with app.state.test_session_factory() as session:
        with pytest.raises(OperationActionError, match="SCHEDULE_NOT_FOUND"):
            await ScheduleService(session, engine).cancel_series(
                root.schedule_id, "other", root.series_version
            )
    async with app.state.test_session_factory() as session:
        series = await session.get(RecurringTransferModel, root.series_id)
        series.scope_json = {**series.scope_json, "amount": "300.00"}
        await session.commit()
    due = rows[0].scheduled_for.replace(tzinfo=UTC) + timedelta(seconds=1)
    await ScheduleWorker(
        app.state.test_session_factory, app.state.event_bus, engine, clock=lambda due=due: due
    ).run_once()
    async with app.state.test_session_factory() as session:
        result = await ScheduleService(session, engine).get(root.schedule_id, ready.user_id)
        assert result.status == "FAILED" and result.operation_id is None
    assert await provider.transfer_count() == 0


async def test_llm_semantic_time_interpretation_is_independent_of_wording():
    import json

    from banking_api.llm.fake_provider import FakeLLMProvider
    from banking_api.llm.models import LLMResponse
    from banking_api.workflows.transfer.time_intent import (
        ExecutionTimeExtractor,
        ExecutionTimeIntent,
        resolve_time_intent,
    )

    now = datetime(2026, 10, 8, 5, tzinfo=UTC)
    provider = FakeLLMProvider(
        [
            LLMResponse(
                content=json.dumps({"kind": "SINGLE", "relative_days": 1, "hour": 9, "minute": 30})
            )
        ]
    )
    intent = await ExecutionTimeExtractor(provider).extract("明早九点半替我安排付款")
    assert resolve_time_intent(intent, now)[0] == datetime(2026, 10, 9, 1, 30, tzinfo=UTC)
    assert resolve_time_intent(
        ExecutionTimeIntent(weekday=5, week_offset=1, hour=15, minute=45), now
    )[0] == datetime(2026, 10, 16, 7, 45, tzinfo=UTC)
    assert resolve_time_intent(ExecutionTimeIntent(relative_minutes=120), now)[
        0
    ] == now + timedelta(hours=2)
    for intent in [
        ExecutionTimeIntent(relative_days=1),
        ExecutionTimeIntent(relative_days=-1, hour=9),
        ExecutionTimeIntent(relative_days=1, date="2026-10-09", hour=9),
        ExecutionTimeIntent(kind="MONTHLY", day=1, hour=9),
    ]:
        with pytest.raises(ValueError):
            resolve_time_intent(intent, now)
    malicious = FakeLLMProvider([LLMResponse(content='{"account_id":"not-allowed"}')] * 2)
    with pytest.raises(ValueError, match="EXTRACTION_UNAVAILABLE"):
        await ExecutionTimeExtractor(malicious).extract("明早九点半")


async def test_short_payee_name_requires_explicit_choice(app):
    from banking_api.application.conversation_service import ConversationService
    from banking_api.domain.enums import WorkflowStatus
    from banking_api.workflows.transfer.models import TransferIntent

    _, _, _, engine = operation_runtime(app)
    async with app.state.test_session_factory() as session:
        service = ConversationService(session, app.state.event_bus)
        conv = await service.create(user_id="dev-user-001", title="简称")
        task = await service.accept_message(
            conversation_id=conv.conversation_id, user_id="dev-user-001", content="给物业转100元"
        )
        workflow = await WorkflowService(session, app.state.event_bus, engine).create_transfer(
            user_id="dev-user-001",
            conversation_id=conv.conversation_id,
            source_task_id=task.task_id,
            intent=TransferIntent(
                recipient_query="物业", amount="100", source_account_hint="工资卡"
            ),
        )
        assert workflow.status == WorkflowStatus.WAITING_FOR_INPUT
        assert workflow.state["required_input"]["type"] == "PAYEE_SELECTION"
        assert workflow.state["draft"]["payee_id"] is None
        options = workflow.state["required_input"]["options"]
        assert len(options) == 1 and options[0]["display_name"] == "青禾物业"
        workflow = await WorkflowService(session, app.state.event_bus, engine).select_payee(
            workflow.workflow_id,
            user_id="dev-user-001",
            payee_id=options[0]["payee_id"],
            expected_version=workflow.version,
        )
        assert workflow.status == WorkflowStatus.READY_FOR_REVIEW


async def test_delete_cancelled_series_as_one_task(app, schedule_enabled):
    _, _, _, engine = operation_runtime(app)
    ready, root, rows = await recurring(app, engine)
    async with app.state.test_session_factory() as session:
        service = ScheduleService(session, engine)
        await service.cancel_series(root.schedule_id, ready.user_id, root.series_version)
        cancelled = await service.get(root.schedule_id, ready.user_id)
        await service.delete_cancelled(root.schedule_id, ready.user_id, cancelled.version)
        assert await service.list(ready.user_id) == []
        for row in rows:
            stored = await session.get(ScheduledTransferModel, row.schedule_id)
            assert stored.deleted_at is not None and stored.status == "CANCELLED"
