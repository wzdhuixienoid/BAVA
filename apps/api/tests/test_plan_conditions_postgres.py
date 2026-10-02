import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import test_postgres_integration
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from test_plan_conditions import (
    balance_output,
    conditional_plan,
)
from test_plan_conditions import (
    test_false_transfer_skips_all_side_effects_and_completes as false_case,
)
from test_plan_conditions import (
    test_stale_condition_worker_cannot_persist_or_start_workflow as stale_case,
)
from test_plan_conditions import (
    test_true_waits_for_user_and_reuses_immutable_decision as handoff_case,
)
from test_plan_postgres import use_postgres
from test_plans import call, get_plan, lock_user, setup_plan

from banking_api.application.operation_recovery_policy import OperationRecoveryPolicy
from banking_api.config.settings import get_settings
from banking_api.llm.models import LLMResponse
from banking_api.persistence.models import OperationModel
from banking_api.persistence.repositories.conversations import ConversationRepository
from banking_api.persistence.repositories.plans import PlanRepository
from banking_api.persistence.repositories.tasks import TaskRepository
from banking_api.planning.condition_evaluator import PlanConditionEvaluator
from banking_api.planning.models import ConditionSpec
from banking_api.planning.validator import PlanValidator
from banking_api.runtime.operation_recovery_worker import OperationRecoveryWorker
from banking_api.subscriptions.provider import SubscriptionProviderFaultMode

pytestmark = pytest.mark.postgres
postgres_factory = test_postgres_integration.postgres_factory


async def test_postgres_0016_to_0017_preserves_legacy_and_persists_condition(postgres_factory):
    settings = get_settings()
    original_url = settings.database_url
    settings.database_url = postgres_factory.kw["bind"].url.render_as_string(hide_password=False)
    api_dir = Path(__file__).parents[1]
    config = Config(str(api_dir / "alembic.ini"))
    config.set_main_option("script_location", str(api_dir / "migrations"))
    try:
        await asyncio.to_thread(command.downgrade, config, "0016")
        # Insert actual legacy rows while only the 0016 schema exists.
        async with postgres_factory() as session:
            conversation = await ConversationRepository(session).create(
                user_id="legacy", title="legacy"
            )
            task = await TaskRepository(session).create(
                conversation_id=conversation.conversation_id,
                user_id="legacy",
                task_type="USER_REQUEST",
                input_data={},
            )
            from uuid import uuid4

            plan_id, source_id = uuid4(), uuid4()
            await session.execute(
                text(
                    "INSERT INTO plans (id,user_id,conversation_id,source_task_id,"
                    "goal_summary,status,version,manual_takeover,created_at,updated_at) "
                    "VALUES (:id,'legacy',:conversation,:task,'legacy','RUNNING',"
                    "1,false,now(),now())"
                ),
                {"id": plan_id, "conversation": conversation.conversation_id, "task": task.task_id},
            )
            await session.execute(
                text(
                    "INSERT INTO plan_steps (id,plan_id,step_key,ordinal,display_title,"
                    "capability,executor_kind,status,output_json) VALUES (:id,:plan,'s0',0,'余额',"
                    "'ACCOUNT_QUERY','AGENT','COMPLETED',cast(:output AS json))"
                ),
                {"id": source_id, "plan": plan_id, "output": json.dumps(balance_output())},
            )
            await session.commit()
        await asyncio.to_thread(command.upgrade, config, "0017")
        async with postgres_factory() as session:
            assert await session.scalar(text("SELECT version_num FROM alembic_version")) == "0017"
            legacy = (await PlanRepository(session).steps(plan_id))[0]
            assert legacy.step_kind == "CAPABILITY" and legacy.capability == "ACCOUNT_QUERY"
            assert legacy.condition_spec_json is None and legacy.output_json == balance_output()
            task = await TaskRepository(session).create(
                conversation_id=conversation.conversation_id,
                user_id="legacy",
                task_type="USER_REQUEST",
                input_data={},
            )
            repository = PlanRepository(session)
            plan = await repository.create(
                PlanValidator().parse(json.dumps(conditional_plan())),
                task_id=task.task_id,
                conversation_id=conversation.conversation_id,
                user_id="legacy",
            )
            steps = await repository.steps(plan.plan_id)
            source, condition, guarded = steps
            source.status = "COMPLETED"
            source.output_json = balance_output()
            spec = ConditionSpec.model_validate_json(json.dumps(condition.condition_spec_json))
            decision = PlanConditionEvaluator().evaluate(
                spec,
                source_step_id=source.step_id,
                source_capability=source.capability,
                source_status=source.status,
                output=source.output_json,
            )
            condition.status = "COMPLETED"
            condition.condition_decision_json = decision.model_dump(mode="json")
            await session.commit()
            assert condition.capability is None and condition.executor_kind == "CONDITION"
            assert guarded.guard_condition_step_id == condition.step_id
            assert len(await repository.dependencies(plan.plan_id)) == 2
        async with postgres_factory() as session:
            persisted = await PlanRepository(session).steps(plan.plan_id)
            assert persisted[1].condition_decision_json == decision.model_dump(mode="json")
            assert persisted[1].condition_spec_json == spec.model_dump(mode="json")
            assert persisted[2].guard_condition_step_id == persisted[1].step_id
    finally:
        await asyncio.to_thread(command.upgrade, config, "head")
        settings.database_url = original_url


async def test_postgres_false_condition_zero_writes(app, client, postgres_factory):
    await use_postgres(app, postgres_factory)
    await false_case(app, client)


async def test_postgres_condition_fencing(app, client, postgres_factory, monkeypatch):
    await use_postgres(app, postgres_factory)
    await stale_case(app, client, monkeypatch)


async def test_postgres_conditional_handoff_takeover_resume(app, client, postgres_factory):
    await use_postgres(app, postgres_factory)
    await handoff_case(app, client)


async def test_postgres_conditional_unknown_existing_operation_survives_lock(
    app, client, postgres_factory
):
    await use_postgres(app, postgres_factory)
    data = conditional_plan("100", "SUBSCRIPTION_CANCEL_WORKFLOW")
    data["steps"][0]["capability"] = "SUBSCRIPTION_ANALYSIS"
    data["steps"][0]["subtask_query"] = "看看我的订阅"
    data["steps"][1]["condition"]["predicate"] = "SUBSCRIPTION_MONTHLY_COST_AT_LEAST"
    runner, planner, _, provider, task_id = await setup_plan(
        app,
        client,
        data=data,
        user_request="如果每月订阅费用不少于100元，取消星幕视频",
        responses=[call("analyze_subscriptions", {}), LLMResponse(content="已查")],
        fault_mode=SubscriptionProviderFaultMode.TIMEOUT_AFTER_ACCEPT,
    )
    await runner.run(task_id)
    plan = await get_plan(app, task_id)
    decision = plan.steps[1].condition_decision
    assert decision.outcome == "TRUE"
    workflow_id = plan.steps[2].linked_workflow_id
    workflow = (await client.get(f"/api/v1/workflows/{workflow_id}")).json()
    for action in ("approve", "commit"):
        response = await client.post(
            f"/api/v1/workflows/{workflow_id}/actions/{action}",
            json={"expected_version": workflow["version"]},
        )
        assert response.status_code == 200, response.text
        workflow = response.json()
    operation_id = workflow["operation_summary"]["operation_id"]
    assert workflow["operation_summary"]["status"] == "UNKNOWN"
    await runner.run(task_id)
    assert (await get_plan(app, task_id)).status == "WAITING_EXTERNAL"
    await lock_user(postgres_factory, "dev-user-001")
    # Existing resource retrieval remains before the new-operation write gate.
    retry = await client.post(
        f"/api/v1/workflows/{workflow_id}/actions/commit",
        json={"expected_version": workflow["version"]},
    )
    assert (
        retry.status_code == 200
        and retry.json()["operation_summary"]["operation_id"] == operation_id
    )
    from uuid import UUID

    async with postgres_factory() as session:
        operation = await session.get(OperationModel, UUID(operation_id))
        operation.next_reconcile_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    worker = OperationRecoveryWorker(
        postgres_factory,
        app.state.event_bus,
        app.state.transfer_workflow_engine,
        subscription_engine=app.state.subscription_workflow_engine,
        policy=OperationRecoveryPolicy.from_settings(),
        poll_interval_seconds=1,
        batch_size=10,
    )
    await worker.run_once()
    await runner.run(task_id)
    final = await get_plan(app, task_id)
    assert final.status == "COMPLETED" and final.steps[1].condition_decision == decision
    assert len(planner.requests) == 1 and await provider.cancellation_count() == 1
    async with postgres_factory() as session:
        assert await session.scalar(select(func.count()).select_from(OperationModel)) == 1
