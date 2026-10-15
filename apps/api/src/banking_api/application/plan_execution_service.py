import json
from typing import TYPE_CHECKING
from uuid import uuid5

from banking_api.application.account_results import build_account_results
from banking_api.application.plan_service import plan_event, step_event
from banking_api.application.workflow_service import WorkflowService
from banking_api.domain.enums import (
    MessageRole,
    OperationStatus,
    RuntimeBackend,
    TaskStatus,
    WorkflowStatus,
)
from banking_api.domain.principal import ExecutionPrincipal
from banking_api.financial.analysis_snapshot import build_financial_analysis_snapshot
from banking_api.llm.provider import LLMProviderError
from banking_api.persistence.models import utc_now
from banking_api.persistence.repositories.messages import MessageRepository
from banking_api.persistence.repositories.operations import OperationRepository
from banking_api.persistence.repositories.plans import PlanRepository
from banking_api.persistence.repositories.tasks import TaskExecutionClaim, TaskRepository
from banking_api.planning.condition_evaluator import (
    ConditionEvaluationError,
    PlanConditionEvaluator,
)
from banking_api.planning.models import ConditionSpec, PlanCapability, PlanStatus, PlanStepStatus
from banking_api.planning.registry import PlanCapabilityRegistry
from banking_api.planning.validator import PlanValidationError, PlanValidator
from banking_api.runtime.base import AgentRunRequest, AgentRuntimeError
from banking_api.runtime.event_publisher import EventPublisher
from banking_api.subscriptions.answers import subscription_answer

if TYPE_CHECKING:
    from banking_api.runtime.task_runner import InProcessTaskRunner

BAD_UPSTREAM = {PlanStepStatus.FAILED, PlanStepStatus.CANCELLED, PlanStepStatus.SKIPPED}


class PlanExecutionService:
    """Small serial DAG orchestrator, always running under the source Task fence."""

    def __init__(self, runner: "InProcessTaskRunner") -> None:
        self.runner = runner
        self.registry = PlanCapabilityRegistry()
        self.condition_evaluator = PlanConditionEvaluator()

    async def execute(self, claim: TaskExecutionClaim, user_request: str) -> None:
        runner = self.runner
        async with runner.session_factory() as session:
            await runner._get_owned(TaskRepository(session), claim)
            plan = await PlanRepository(session).by_task(claim.task_id)
        if plan is None:
            if runner.planner is None:
                raise PlanValidationError("PLAN_PLANNER_NOT_CONFIGURED")
            try:
                validated = await runner.planner.propose(user_request)
                validated = PlanValidator().validate_grounding(validated, user_request)
            except LLMProviderError as exc:
                raise AgentRuntimeError(
                    "PLAN_PLANNER_UNAVAILABLE", "规划服务暂时不可用", retryable=exc.retryable
                ) from exc
            async with runner.session_factory() as session:
                await runner._get_owned(TaskRepository(session), claim, for_update=True)
                repository = PlanRepository(session)
                plan = await repository.by_task(claim.task_id)
                if plan is None:
                    plan = await repository.create(
                        validated,
                        task_id=claim.task_id,
                        conversation_id=claim.conversation_id,
                        user_id=claim.user_id,
                    )
                    await plan_event(session, plan, "PLAN_CREATED")
                await session.commit()
        plan_id = plan.plan_id
        while True:
            async with runner.session_factory() as session:
                await runner._get_owned(TaskRepository(session), claim, for_update=True)
                repository = PlanRepository(session)
                plan = await repository.get(plan_id, claim.user_id, lock=True)
                assert plan is not None
                if plan.manual_takeover:
                    return
                steps = await repository.steps(plan_id)
                dependencies = await repository.dependencies(plan_id)
                by_id = {step.step_id: step for step in steps}
                # Propagate failures transitively, independent of proposal ordinal.
                changed = True
                while changed:
                    changed = False
                    for step in steps:
                        if step.status == PlanStepStatus.PENDING and any(
                            by_id[parent].status in BAD_UPSTREAM
                            for parent in dependencies.get(step.step_id, [])
                        ):
                            step.status = PlanStepStatus.SKIPPED
                            parents = [
                                by_id[parent] for parent in dependencies.get(step.step_id, [])
                            ]
                            step.error_code = (
                                "CONDITION_NOT_MET"
                                if not any(
                                    parent.status
                                    in {PlanStepStatus.FAILED, PlanStepStatus.CANCELLED}
                                    or (
                                        parent.status == PlanStepStatus.SKIPPED
                                        and parent.error_code != "CONDITION_NOT_MET"
                                    )
                                    for parent in parents
                                )
                                else "UPSTREAM_NOT_COMPLETED"
                            )
                            step.completed_at = utc_now()
                            await step_event(session, plan, step)
                            changed = True
                # Decisions and directly guarded skips are persisted atomically below.
                for step in steps:
                    if step.status == PlanStepStatus.PENDING and step.guard_condition_step_id:
                        guard = by_id[step.guard_condition_step_id]
                        if guard.status == PlanStepStatus.COMPLETED:
                            decision = guard.condition_decision_json
                            if not decision or decision.get("outcome") not in {"TRUE", "FALSE"}:
                                raise PlanValidationError("CONDITION_INPUT_UNAVAILABLE")
                            if decision["outcome"] == "FALSE":
                                step.status = PlanStepStatus.SKIPPED
                                step.error_code = "CONDITION_NOT_MET"
                                step.completed_at = utc_now()
                                await step_event(session, plan, step)
                candidate = next(
                    (
                        step
                        for step in steps
                        if (
                            step.status
                            in {
                                PlanStepStatus.RUNNING,
                                PlanStepStatus.WAITING_USER,
                                PlanStepStatus.WAITING_EXTERNAL,
                            }
                            or (
                                step.status == PlanStepStatus.PENDING
                                and all(
                                    by_id[parent].status == PlanStepStatus.COMPLETED
                                    for parent in dependencies.get(step.step_id, [])
                                )
                            )
                        )
                    ),
                    None,
                )
                if candidate is None:
                    await self._finish(session, claim, plan, steps)
                    return
                candidate.status = PlanStepStatus.RUNNING
                candidate.started_at = candidate.started_at or utc_now()
                await step_event(session, plan, candidate)
                await session.commit()
                step_id = candidate.step_id
                capability = PlanCapability(candidate.capability) if candidate.capability else None
                step_kind = candidate.step_kind
                subtask_query = candidate.subtask_query
            try:
                decision = None
                if step_kind == "CONDITION":
                    decision = await self._condition(claim, plan_id, step_id)
                    output = None
                    status = PlanStepStatus.COMPLETED
                    workflow_id = None
                elif self.registry.get(capability).read_only:
                    output = await self._read(
                        claim, step_id, capability, subtask_query or user_request
                    )
                    status = PlanStepStatus.COMPLETED
                    workflow_id = None
                else:
                    workflow_id = await self._workflow(claim, capability, user_request)
                    output = None
                    status = None
            except (AgentRuntimeError, ConditionEvaluationError) as exc:
                if exc.retryable:
                    raise
                async with runner.session_factory() as session:
                    await runner._get_owned(TaskRepository(session), claim, for_update=True)
                    repository = PlanRepository(session)
                    plan = await repository.get(plan_id, claim.user_id, lock=True)
                    step = next(s for s in await repository.steps(plan_id) if s.step_id == step_id)
                    step.status = PlanStepStatus.FAILED
                    step.error_code = exc.code
                    step.error_message = "该步骤执行失败，可查看错误代码或安全回退后重试"
                    step.completed_at = utc_now()
                    assert plan is not None
                    await step_event(session, plan, step)
                    await session.commit()
                continue
            async with runner.session_factory() as session:
                task = await runner._get_owned(TaskRepository(session), claim, for_update=True)
                repository = PlanRepository(session)
                plan = await repository.get(plan_id, claim.user_id, lock=True)
                assert plan is not None
                step = next(s for s in await repository.steps(plan_id) if s.step_id == step_id)
                if decision is not None:
                    if step.condition_decision_json is not None:
                        raise PlanValidationError("CONDITION_DECISION_ALREADY_PERSISTED")
                    step.condition_decision_json = decision.model_dump(mode="json")
                    if decision.outcome == "FALSE":
                        for guarded in await repository.steps(plan_id):
                            if (
                                guarded.guard_condition_step_id == step_id
                                and guarded.status == PlanStepStatus.PENDING
                            ):
                                guarded.status = PlanStepStatus.SKIPPED
                                guarded.error_code = "CONDITION_NOT_MET"
                                guarded.completed_at = utc_now()
                                await step_event(session, plan, guarded)
                if workflow_id is not None:
                    step.linked_workflow_id = workflow_id
                    service = self._workflow_service(session)
                    workflow = await service.get(workflow_id, user_id=claim.user_id)
                    operation = await OperationRepository(session).get_for_workflow(
                        workflow_id, claim.user_id
                    )
                    if (
                        workflow.status == WorkflowStatus.SUCCEEDED
                        and operation is not None
                        and operation.status == OperationStatus.SUCCEEDED
                    ):
                        status = PlanStepStatus.COMPLETED
                        output = {
                            "workflow_id": str(workflow_id),
                            "workflow_type": workflow.workflow_type.value,
                            "workflow_status": workflow.status.value,
                            "operation_id": str(operation.operation_id),
                            "operation_status": operation.status.value,
                        }
                    elif workflow.status == WorkflowStatus.FAILED:
                        status = PlanStepStatus.FAILED
                        step.error_code = "CHILD_WORKFLOW_FAILED"
                    elif workflow.status == WorkflowStatus.CANCELLED:
                        status = PlanStepStatus.CANCELLED
                        step.error_code = "CHILD_WORKFLOW_CANCELLED"
                    elif workflow.status == WorkflowStatus.COMMITTING or operation is not None:
                        status = PlanStepStatus.WAITING_EXTERNAL
                    else:
                        status = PlanStepStatus.WAITING_USER
                assert status is not None
                step.status = status
                step.output_json = output
                if status in {PlanStepStatus.COMPLETED, *BAD_UPSTREAM}:
                    step.completed_at = utc_now()
                plan.version += 1
                plan.updated_at = utc_now()
                await step_event(session, plan, step)
                if status in {PlanStepStatus.WAITING_USER, PlanStepStatus.WAITING_EXTERNAL}:
                    plan.status = PlanStatus(status.value)
                    await TaskRepository(session).transition(
                        task,
                        TaskStatus(status.value),
                        output={"plan_id": str(plan_id)},
                        progress_message=(
                            "前置步骤已完成，下一步需要你的操作"
                            if status == PlanStepStatus.WAITING_USER
                            else "正在等待原业务操作的外部结果"
                        ),
                    )
                    await plan_event(session, plan, "CHILD_" + status.value)
                    await EventPublisher(session).persist(
                        event_type="task." + status.value.lower(),
                        conversation_id=claim.conversation_id,
                        task_id=claim.task_id,
                        data={"plan_id": str(plan_id), "status": task.status.value},
                    )
                    await session.commit()
                    return
                plan.status = PlanStatus.RUNNING
                await session.commit()

    async def _condition(self, claim, plan_id, step_id):  # type: ignore[no-untyped-def]
        async with self.runner.session_factory() as session:
            await self.runner._get_owned(TaskRepository(session), claim)
            steps = await PlanRepository(session).steps(plan_id)
            step = next(s for s in steps if s.step_id == step_id)
            try:
                spec = ConditionSpec.model_validate_json(json.dumps(step.condition_spec_json))
                source = next(s for s in steps if s.step_key == spec.source_step_key)
            except (ValueError, StopIteration) as exc:
                raise ConditionEvaluationError("CONDITION_INPUT_UNAVAILABLE") from exc
            return self.condition_evaluator.evaluate(
                spec,
                source_step_id=source.step_id,
                source_capability=source.capability,
                source_status=source.status,
                output=source.output_json,
            )

    async def _read(self, claim, step_id, capability, query):  # type: ignore[no-untyped-def]
        runner = self.runner
        definition = self.registry.get(capability)
        agent = runner._get_agent(definition.executor_id)
        from banking_api.agents.personal_banking_agent import (
            PERSONAL_BANKING_AGENT_ID,
            PersonalBankingMode,
            personal_banking_agent,
        )

        if agent.agent_id == PERSONAL_BANKING_AGENT_ID:
            agent = personal_banking_agent(
                PersonalBankingMode.SPENDING
                if capability == PlanCapability.FINANCIAL_ANALYSIS
                else PersonalBankingMode.ACCOUNT
            )
        if capability == PlanCapability.FINANCIAL_ANALYSIS and (
            claim.runtime_backend != RuntimeBackend.LANGGRAPH
        ):
            raise AgentRuntimeError("FINANCIAL_AGENT_REQUIRES_LANGGRAPH", "需要 LangGraph runtime")

        async def sink(event_type, data):  # type: ignore[no-untyped-def]
            await runner._persist_runtime_event(
                claim=claim,
                conversation_id=claim.conversation_id,
                event_type=event_type,
                data={**data, "plan_step_id": str(step_id)},
            )

        result = await runner.runtime_factory.get(claim.runtime_backend).run(
            AgentRunRequest(
                # Isolate checkpoints of each step/attempt; no new durable Task or lease.
                task_id=uuid5(step_id, str(claim.attempt)),
                conversation_id=claim.conversation_id,
                current_task=query,
                conversation_messages=[],
                principal=ExecutionPrincipal.for_task(claim.user_id),
                agent=agent,
                event_sink=sink,
            )
        )
        facts = result.state.successful_tool_results
        if not facts:
            raise AgentRuntimeError("PLAN_READ_RESULT_MISSING", "未取得可信结构化结果")
        if capability == PlanCapability.FINANCIAL_ANALYSIS:
            if not any(f.capability_id.startswith("transaction.") for f in facts):
                raise AgentRuntimeError("PLAN_READ_RESULT_MISSING", "未取得金融分析结果")
            output = {
                "analysis_snapshot": build_financial_analysis_snapshot(facts).model_dump(
                    mode="json"
                )
            }
            anomaly = next(
                (
                    f.output["snapshot"]
                    for f in facts
                    if f.capability_id == "transaction.detect_anomalies" and "snapshot" in f.output
                ),
                None,
            )
            if anomaly is not None:
                output["transaction_anomaly_snapshot"] = anomaly
                output["transaction_anomaly_answer"] = result.answer
                output["anomaly_skill_id"] = "skill:transaction-anomaly-analysis"
        elif capability == PlanCapability.SUBSCRIPTION_ANALYSIS:
            from banking_api.subscriptions.models import SubscriptionAnalysisSnapshot

            snapshot = next(
                (f.output["snapshot"] for f in facts if f.capability_id == "subscription.analyze"),
                None,
            )
            if snapshot is None:
                raise AgentRuntimeError("PLAN_READ_RESULT_MISSING", "未取得订阅快照")
            output = {
                "subscription_analysis_snapshot": SubscriptionAnalysisSnapshot.model_validate(
                    snapshot
                ).model_dump(mode="json")
            }
        else:
            output = {
                "account_results": [
                    result.model_dump(mode="json") for result in build_account_results(facts)
                ],
                "payee_results": [
                    item.output
                    for item in facts
                    if item.capability_id in {"payee.list", "payee.search"}
                ],
            }
        if len(json.dumps(output, ensure_ascii=False).encode()) > 65536:
            raise AgentRuntimeError("PLAN_OUTPUT_TOO_LARGE", "结构化结果超过计划存储上限")
        return output

    def _workflow_service(self, session):  # type: ignore[no-untyped-def]
        return WorkflowService(
            session,
            self.runner.bus,
            self.runner.transfer_workflow_engine,
            subscription_engine=self.runner.subscription_workflow_engine,
        )

    async def _workflow(self, claim, capability, original):  # type: ignore[no-untyped-def]
        runner = self.runner
        async with runner.session_factory() as session:
            await runner._get_owned(TaskRepository(session), claim)
            workflow = await self._workflow_service(session).get_by_source_task(
                claim.task_id, user_id=claim.user_id
            )
        if workflow is not None:
            return workflow.workflow_id
        extractor = (
            runner.transfer_intent_extractor
            if capability == PlanCapability.TRANSFER_WORKFLOW
            else runner.subscription_intent_extractor
        )
        if extractor is None:
            raise AgentRuntimeError("PLAN_WORKFLOW_NOT_CONFIGURED", "业务 Workflow 未配置")
        # Only the original source Message is business intent authority.
        intent = await extractor.extract(original)
        async with runner.session_factory() as session:
            await runner._get_owned(TaskRepository(session), claim, for_update=True)
            service = self._workflow_service(session)
            workflow = await service.get_by_source_task(claim.task_id, user_id=claim.user_id)
            if workflow is None:

                async def execution_check():
                    await runner._get_owned(TaskRepository(session), claim, for_update=True)

                create = (
                    service.create_transfer
                    if capability == PlanCapability.TRANSFER_WORKFLOW
                    else service.create_subscription_resume
                    if capability == PlanCapability.SUBSCRIPTION_RESUME_WORKFLOW
                    else service.create_subscription_cancel
                )
                workflow = await create(
                    user_id=claim.user_id,
                    conversation_id=claim.conversation_id,
                    source_task_id=claim.task_id,
                    intent=intent,
                    execution_check=execution_check,
                )
            return workflow.workflow_id

    async def _finish(self, session, claim, plan, steps):  # type: ignore[no-untyped-def]
        task = await self.runner._get_owned(TaskRepository(session), claim, for_update=True)
        success = all(
            step.status == PlanStepStatus.COMPLETED
            or (step.status == PlanStepStatus.SKIPPED and step.error_code == "CONDITION_NOT_MET")
            for step in steps
        )
        plan.status = PlanStatus.COMPLETED if success else PlanStatus.FAILED
        plan.version += 1
        plan.updated_at = utc_now()
        plan.completed_at = utc_now()
        output = {"plan_id": str(plan.plan_id)}
        if success:
            assistant = await MessageRepository(session).create(
                conversation_id=claim.conversation_id,
                role=MessageRole.ASSISTANT,
                content=format_plan_answer(steps),
            )
            output["assistant_message_id"] = str(assistant.message_id)
            await EventPublisher(session).persist(
                event_type="conversation.message.completed",
                conversation_id=claim.conversation_id,
                task_id=claim.task_id,
                data={"message_id": str(assistant.message_id), "role": "ASSISTANT"},
            )
        await TaskRepository(session).transition(
            task,
            TaskStatus.COMPLETED if success else TaskStatus.FAILED,
            output=output,
            error=None if success else {"code": "PLAN_STEP_FAILED", "retryable": False},
        )
        await plan_event(session, plan, "ALL_STEPS_COMPLETED" if success else "PLAN_STEP_FAILED")
        await EventPublisher(session).persist(
            event_type="task.completed" if success else "task.failed",
            conversation_id=claim.conversation_id,
            task_id=claim.task_id,
            data={
                "status": task.status.value,
                "plan_id": str(plan.plan_id),
                "version": task.version,
            },
        )
        await session.commit()


def format_plan_answer(steps) -> str:  # type: ignore[no-untyped-def]
    """Render only persisted bounded facts; free-form Agent answers are not inputs."""
    parts = []
    titles = {
        "ACCOUNT_QUERY": "账户查询",
        "FINANCIAL_ANALYSIS": "消费分析",
        "SUBSCRIPTION_ANALYSIS": "订阅分析",
        "TRANSFER_WORKFLOW": "转账结果",
        "SUBSCRIPTION_CANCEL_WORKFLOW": "订阅取消结果",
        "SUBSCRIPTION_RESUME_WORKFLOW": "订阅恢复结果",
    }
    for step in steps:
        if step.step_kind == "CONDITION":
            decision = step.condition_decision_json
            if decision:
                descriptions = {
                    "ACCOUNT_BALANCE_AT_LEAST": "账户余额",
                    "MONTHLY_SPENDING_AT_LEAST": "本月支出",
                    "SUBSCRIPTION_MONTHLY_COST_AT_LEAST": "每月订阅成本",
                }
                parts.append(
                    f"条件：{descriptions[decision['predicate']]}不少于 "
                    f"{decision['threshold_value']} {decision['currency']}；实际 "
                    f"{decision['actual_value']} {decision['currency']}，"
                    + ("已满足。" if decision["outcome"] == "TRUE" else "未满足。")
                )
            continue
        if step.status == PlanStepStatus.SKIPPED and step.error_code == "CONDITION_NOT_MET":
            parts.append(
                "条件未满足，因此没有启动后续"
                + (
                    "转账流程。"
                    if step.capability == "TRANSFER_WORKFLOW"
                    else "订阅恢复流程。"
                    if step.capability == "SUBSCRIPTION_RESUME_WORKFLOW"
                    else "订阅取消流程。"
                    if step.capability == "SUBSCRIPTION_CANCEL_WORKFLOW"
                    else "查询步骤。"
                )
            )
            continue
        facts = step.output_json or {}
        lines = []
        for account in facts.get("account_results", []):
            if "balance" in account:
                lines.append(
                    f"{account.get('display_name', account['account_id'])}："
                    f"余额 {account['balance']} {account['currency']}"
                )
            for item in account.get("accounts", []):
                lines.append(f"{item.get('display_name', item.get('account_id', '账户'))}")
        analysis = facts.get("analysis_snapshot", {})
        summary = analysis.get("spending_summary")
        if summary:
            lines.append(
                f"{summary['period']}：支出 {summary['total_spending']} {summary['currency']}，"
                f"收入 {summary['total_income']} {summary['currency']}"
            )
        breakdown = analysis.get("category_breakdown")
        if breakdown:
            lines.extend(
                f"{category['category']}：{category['amount']} {breakdown['currency']}"
                for category in breakdown["categories"]
            )
        subscriptions = facts.get("subscription_analysis_snapshot", {})
        for item in subscriptions.get("subscriptions", []):
            lines.append(
                f"{item.get('display_name', item.get('merchant', '订阅'))}："
                f"{item.get('last_charge_amount', '')} {item.get('currency', '')}"
            )
        if facts.get("operation_status") == "SUCCEEDED":
            lines.append(
                {
                    "TRANSFER": "转账成功。",
                    "SUBSCRIPTION_CANCEL": "订阅已取消。",
                    "SUBSCRIPTION_RESUME": "订阅已恢复续费，本次未扣款。",
                }[facts["workflow_type"]]
            )
        if not lines:
            lines.append(json.dumps(facts, ensure_ascii=False, separators=(",", ":")))
        parts.append("\n".join([titles[step.capability], *lines]))
    answer = "\n\n".join(parts)
    return (
        subscription_answer(answer)
        if any("SUBSCRIPTION" in str(step.capability) for step in steps)
        else answer
    )


async def fail_plan(session, task_id, code):  # type: ignore[no-untyped-def]
    """Caller holds the source Task fence; failure and Event/Outbox are atomic."""
    repository = PlanRepository(session)
    plan = await repository.by_task(task_id)
    if plan is None:
        return
    plan = await repository.get(plan.plan_id, plan.user_id, lock=True)
    assert plan is not None
    for step in await repository.steps(plan.plan_id):
        if step.status == PlanStepStatus.RUNNING:
            step.status = PlanStepStatus.FAILED
            step.error_code = code
            step.completed_at = utc_now()
            await step_event(session, plan, step)
        elif step.status == PlanStepStatus.PENDING:
            step.status = PlanStepStatus.SKIPPED
            step.error_code = "PLAN_EXECUTION_ABORTED"
            step.completed_at = utc_now()
            await step_event(session, plan, step)
    plan.status = PlanStatus.FAILED
    plan.version += 1
    plan.completed_at = utc_now()
    plan.updated_at = utc_now()
    await plan_event(session, plan, code)
