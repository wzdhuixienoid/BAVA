import importlib.util
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from banking_test_helpers import authenticate_workflow
from sqlalchemy import func, select
from test_postgres_integration import postgres_factory  # noqa: F401
from test_transfer_authorization import create_ready_workflow
from test_transfer_operations import operation_runtime

from banking_api.application.operation_service import OperationService
from banking_api.application.workflow_service import WorkflowService
from banking_api.persistence.models import (
    ConversationModel,
    MockBankTransferModel,
    MockSubscriptionCancellationModel,
    SecurityGuardStateModel,
    TaskModel,
)

spec = importlib.util.spec_from_file_location(
    "reset_demo_state", Path(__file__).parents[3] / "scripts/reset_demo_state.py"
)
reset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reset)


@pytest.mark.parametrize("environment, stopped", [("production", True), ("development", False)])
async def test_reset_denies_before_database_access(environment, stopped):
    def forbidden_factory():
        raise AssertionError("must not connect")

    with pytest.raises(ValueError):
        await reset.reset_demo_state(
            forbidden_factory,
            environment=environment,
            workers_stopped=stopped,
            user_id="dev-user-001",
        )


async def test_demo_reset_restores_balance_guard_and_subscription_and_preserves_other_owner(app):
    _, provider, _, engine = operation_runtime(app)
    for user in ("dev-user-001", "operation-user"):
        workflow = await create_ready_workflow(
            app, app.state.event_bus, engine, user_id=user, amount=Decimal("500")
        )
        async with app.state.test_session_factory() as session:
            ready = await WorkflowService(session, app.state.event_bus, engine).approve(
                workflow.workflow_id, user_id=user, expected_version=workflow.version
            )
        ready = await authenticate_workflow(app, engine, ready)
        async with app.state.test_session_factory() as session:
            await OperationService(session, app.state.event_bus, engine).commit_workflow(
                ready.workflow_id, user_id=user, expected_version=ready.version
            )
    async with app.state.test_session_factory() as session:
        guard = await session.get(SecurityGuardStateModel, "dev-user-001")
        guard.locked_until = datetime.now(UTC) + timedelta(minutes=15)
        session.add(
            MockSubscriptionCancellationModel(
                user_id="dev-user-001",
                subscription_id="sub_video",
                provider_reference="reset-sub",
                idempotency_key=workflow.workflow_id,
                status="SUCCEEDED",
            )
        )
        await session.commit()
    assert await provider.effective_balance("dev-user-001", "acc_salary") == Decimal("23364.52")
    counts = await reset.reset_demo_state(
        app.state.test_session_factory,
        environment="test",
        workers_stopped=True,
        user_id="dev-user-001",
    )
    assert counts["mock_bank_transfers"] == 1
    assert counts["mock_subscription_cancellations"] == 1
    assert counts["security_guard_states"] == 1
    assert await provider.effective_balance("dev-user-001", "acc_salary") == Decimal("23864.52")
    assert await provider.effective_balance("operation-user", "acc_salary") == Decimal("23364.52")
    async with app.state.test_session_factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ConversationModel)
                .where(ConversationModel.user_id == "dev-user-001")
            )
            == 0
        )
        assert await session.scalar(select(func.count()).select_from(MockBankTransferModel)) == 1
    second = await reset.reset_demo_state(
        app.state.test_session_factory,
        environment="test",
        workers_stopped=True,
        user_id="dev-user-001",
    )
    assert all(count == 0 for count in second.values())


async def test_reset_active_lease_rolls_back(app):
    _, _, _, engine = operation_runtime(app)
    workflow = await create_ready_workflow(app, app.state.event_bus, engine, user_id="dev-user-001")
    async with app.state.test_session_factory() as session:
        task = await session.get(TaskModel, workflow.source_task_id)
        task.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        await session.commit()
    with pytest.raises(ValueError, match="Active execution lease"):
        await reset.reset_demo_state(
            app.state.test_session_factory,
            environment="test",
            workers_stopped=True,
            user_id="dev-user-001",
        )
    async with app.state.test_session_factory() as session:
        assert await session.get(TaskModel, workflow.source_task_id)


@pytest.mark.postgres
async def test_postgres_reset_clears_plan_and_owned_checkpoints_preserves_migrations(
    postgres_factory,  # noqa: F811
):
    from types import SimpleNamespace
    from uuid import uuid4, uuid5

    from sqlalchemy import text

    from banking_api.persistence.models import PlanModel, PlanStepModel
    from banking_api.runtime.event_bus import EventBus
    from banking_api.runtime.langgraph.checkpoint import LangGraphCheckpointManager

    factory = postgres_factory
    application = SimpleNamespace(
        state=SimpleNamespace(test_session_factory=factory, event_bus=EventBus())
    )
    _, provider, _, engine = operation_runtime(application)
    workflow = await create_ready_workflow(
        application,
        application.state.event_bus,
        engine,
        user_id="dev-user-001",
        amount=Decimal("500"),
    )
    plan_id, source_id, condition_id, write_id = (uuid4() for _ in range(4))
    async with factory() as session:
        task = await session.get(TaskModel, workflow.source_task_id)
        task.execution_attempts = 2
        session.add(
            PlanModel(
                plan_id=plan_id,
                user_id="dev-user-001",
                conversation_id=workflow.conversation_id,
                source_task_id=task.task_id,
                goal_summary="reset plan",
                status="WAITING_USER",
            )
        )
        await session.flush()
        session.add(
            PlanStepModel(
                step_id=source_id,
                plan_id=plan_id,
                step_key="source",
                ordinal=0,
                display_title="read",
                executor_kind="AGENT",
                status="COMPLETED",
            )
        )
        session.add(
            PlanStepModel(
                step_id=condition_id,
                plan_id=plan_id,
                step_key="condition",
                ordinal=1,
                display_title="condition",
                step_kind="CONDITION",
                executor_kind="CONDITION",
                status="COMPLETED",
            )
        )
        await session.flush()
        session.add(
            PlanStepModel(
                step_id=write_id,
                plan_id=plan_id,
                step_key="write",
                ordinal=2,
                display_title="transfer",
                executor_kind="WORKFLOW",
                status="WAITING_USER",
                linked_workflow_id=workflow.workflow_id,
                guard_condition_step_id=condition_id,
            )
        )
        await session.execute(
            text(
                "INSERT INTO plan_step_dependencies(step_id, depends_on_step_id) "
                "VALUES (:step, :source)"
            ),
            {"step": condition_id, "source": source_id},
        )
        await session.commit()
    from test_postgres_integration import TEST_DATABASE_URL

    manager = LangGraphCheckpointManager(TEST_DATABASE_URL)
    await manager.start()
    await manager.close()
    threads = [str(workflow.source_task_id), str(uuid5(source_id, "1")), str(uuid5(source_id, "2"))]
    unrelated_thread = str(uuid4())
    async with factory() as session:
        migration_head = await session.scalar(text("SELECT version_num FROM alembic_version"))
        checkpoint_version = await session.scalar(text("SELECT max(v) FROM checkpoint_migrations"))
        for thread in [*threads, unrelated_thread]:
            await session.execute(
                text(
                    "INSERT INTO checkpoints(thread_id, checkpoint_id, checkpoint) "
                    "VALUES (:thread, 'reset-test', '{}')"
                ),
                {"thread": thread},
            )
        await session.commit()
    counts = await reset.reset_demo_state(
        factory, environment="test", workers_stopped=True, user_id="dev-user-001"
    )
    assert counts["checkpoints"] == 3
    async with factory() as session:
        assert (
            await session.scalar(text("SELECT version_num FROM alembic_version")) == migration_head
        )
        assert (
            await session.scalar(text("SELECT max(v) FROM checkpoint_migrations"))
            == checkpoint_version
        )
        assert await session.scalar(select(func.count()).select_from(PlanModel)) == 0
        assert await session.scalar(select(func.count()).select_from(PlanStepModel)) == 0
        assert (
            await session.scalar(
                text("SELECT count(*) FROM checkpoints WHERE thread_id=:thread"),
                {"thread": unrelated_thread},
            )
            == 1
        )
        await session.execute(
            text("DELETE FROM checkpoints WHERE thread_id=:thread"), {"thread": unrelated_thread}
        )
        await session.commit()
    assert await provider.effective_balance("dev-user-001", "acc_salary") == Decimal("23864.52")
