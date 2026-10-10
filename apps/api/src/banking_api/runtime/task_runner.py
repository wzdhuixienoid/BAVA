import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from banking_api.agents.financial_analysis_agent import FINANCIAL_ANALYSIS_AGENT_ID
from banking_api.agents.minimal_banking_agent import MINIMAL_BANKING_AGENT
from banking_api.agents.models import AgentDefinition
from banking_api.agents.subscription_analysis_agent import SUBSCRIPTION_ANALYSIS_AGENT_ID
from banking_api.application.account_results import build_account_results
from banking_api.application.conversation_service import to_message
from banking_api.application.plan_execution_service import PlanExecutionService, fail_plan
from banking_api.application.report_service import (
    ReportPersistenceError,
    ReportService,
)
from banking_api.application.task_execution_policy import TaskExecutionPolicy
from banking_api.application.workflow_service import WorkflowService
from banking_api.domain.enums import (
    ExecutorType,
    MessageRole,
    ReportType,
    RequestedOutput,
    RuntimeBackend,
    TaskStatus,
    WorkflowStatus,
)
from banking_api.domain.principal import ExecutionPrincipal
from banking_api.financial.analysis_snapshot import (
    FinancialAnalysisSnapshot,
    build_financial_analysis_snapshot,
)
from banking_api.financial.report_models import MonthlySpendingReport
from banking_api.persistence.repositories.conversations import ConversationRepository
from banking_api.persistence.repositories.messages import MessageRepository
from banking_api.persistence.repositories.tasks import TaskExecutionClaim, TaskRepository
from banking_api.planning.planner import ConstrainedPlanner
from banking_api.planning.validator import PlanValidationError
from banking_api.registries.agent_registry import AgentRegistry
from banking_api.registries.skill_registry import SkillRegistry
from banking_api.routing.models import RequestRoute, RouteDecision
from banking_api.routing.request_router import RequestRouter, RoutingError
from banking_api.runtime.base import (
    AgentRunRequest,
    AgentRuntimeError,
    SuccessfulToolResult,
)
from banking_api.runtime.event_bus import EventBus
from banking_api.runtime.event_publisher import EventPublisher
from banking_api.runtime.runtime_factory import AgentRuntimeFactory
from banking_api.runtime.task_execution_worker import (
    TaskExecutionWorker,
    TaskLeaseLostError,
)
from banking_api.skill_runtime.executor import (
    SkillErrorCode,
    SkillExecutionError,
    SkillExecutor,
)
from banking_api.skills.models import SkillDefinition
from banking_api.skills.monthly_spending_report import (
    MONTHLY_SPENDING_REPORT_SKILL_ID,
)
from banking_api.subscriptions.answers import subscription_answer
from banking_api.workflows.subscription_cancel.engine import SubscriptionCancellationWorkflow
from banking_api.workflows.subscription_cancel.intent_extractor import (
    SubscriptionCancelIntentExtractionError,
    SubscriptionCancelIntentExtractor,
)
from banking_api.workflows.transfer.engine import TransferWorkflowEngine
from banking_api.workflows.transfer.intent_extractor import (
    TransferIntentExtractionError,
    TransferIntentExtractor,
)

UNSUPPORTED_MESSAGE = "当前无法安全处理该请求。暂不支持条件自动执行或当前能力之外的业务。"

ROUTE_AGENT_IDS = {
    RequestRoute.WEALTH_ANALYSIS: "agent:wealth-advisor",
    RequestRoute.MINIMAL_BANKING: MINIMAL_BANKING_AGENT.agent_id,
    RequestRoute.FINANCIAL_ANALYSIS: FINANCIAL_ANALYSIS_AGENT_ID,
    RequestRoute.SUBSCRIPTION_ANALYSIS: SUBSCRIPTION_ANALYSIS_AGENT_ID,
}
TRANSFER_WORKFLOW_ID = "workflow:transfer"
SUBSCRIPTION_WORKFLOW_ID = "workflow:subscription-cancel"
SUBSCRIPTION_RESUME_WORKFLOW_ID = "workflow:subscription-resume"

REPORT_SOURCE_INSTRUCTIONS = """
本次请求的产品输出是月度消费报告数据源。
必须成功获取 spending_summary 和 category_breakdown。
优先同时获取 period_comparison 和 top_transactions。
如果先查询了账户，剩余三个工具名额必须优先汇总、分类，再选一项可选数据。
任何必需查询返回没有账单时立即结束，不补查可选数据或猜测其他期间。
top_transactions 使用 limit=5，以保持报告 Artifact 的有界展示范围。
不得固定 Tool 调用顺序，也不得自行计算数值。
中间自然语言回答不会展示给用户；只需在数据收集完成后简短结束。
""".strip()

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


class InProcessTaskRunner:
    """Executes an already-claimed Task through existing application runtimes."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bus: EventBus,
        runtime_factory: AgentRuntimeFactory,
        default_backend: RuntimeBackend = RuntimeBackend.MANUAL,
        router: RequestRouter | None = None,
        agent_registry: AgentRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
        skill_executor: SkillExecutor | None = None,
        aa_intent_extractor=None,
        aa_bank=None,
        transfer_intent_extractor: TransferIntentExtractor | None = None,
        transfer_workflow_engine: TransferWorkflowEngine | None = None,
        subscription_intent_extractor: SubscriptionCancelIntentExtractor | None = None,
        subscription_workflow_engine: SubscriptionCancellationWorkflow | None = None,
        planner: ConstrainedPlanner | None = None,
        clock=_now,  # type: ignore[no-untyped-def]
    ) -> None:
        self.session_factory = session_factory
        self.bus = bus
        self.runtime_factory = runtime_factory
        self.default_backend = default_backend
        self.router = router
        self.agent_registry = agent_registry
        self.skill_registry = skill_registry
        self.skill_executor = skill_executor
        self.aa_intent_extractor, self.aa_bank = aa_intent_extractor, aa_bank
        self.transfer_intent_extractor = transfer_intent_extractor
        self.transfer_workflow_engine = transfer_workflow_engine
        self.subscription_intent_extractor = subscription_intent_extractor
        self.subscription_workflow_engine = subscription_workflow_engine
        self.planner = planner
        self.clock = clock

    async def run(self, task_id: UUID) -> None:
        """Compatibility/test entry point using the durable claim path."""
        policy = TaskExecutionPolicy.from_settings()
        worker = TaskExecutionWorker(
            self.session_factory,
            self,
            policy=policy,
            poll_interval_seconds=policy.heartbeat_interval.total_seconds(),
            batch_size=1,
            max_concurrency=1,
        )
        await worker.run_task_once(task_id)

    async def execute_claimed(
        self, claim: TaskExecutionClaim, *, policy: TaskExecutionPolicy
    ) -> None:
        task_id = claim.task_id
        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            messages = MessageRepository(session)
            task = await self._get_owned(tasks, claim)
            message_id = UUID(str(task.input_json["message_id"]))
            current_message = await messages.get(message_id)
            if current_message is None:
                await session.rollback()
                await self._fail(
                    claim,
                    task.conversation_id,
                    {
                        "category": "INPUT",
                        "code": "TASK_INPUT_MISSING",
                        "message": "Task input message no longer exists",
                        "retryable": False,
                    },
                    policy=policy,
                )
                return
            conversation_messages = [
                to_message(message)
                for message in await messages.list_for_conversation(task.conversation_id)
            ]
            current_task = current_message.content
            conversation_id = task.conversation_id
            conversation = await ConversationRepository(session).get(conversation_id)
            if conversation is None:
                await session.rollback()
                await self._fail(
                    claim,
                    conversation_id,
                    {
                        "category": "INPUT",
                        "code": "TASK_CONVERSATION_MISSING",
                        "message": "Task conversation no longer exists",
                        "retryable": False,
                    },
                    policy=policy,
                )
                return
            if conversation.user_id != task.user_id or claim.user_id != task.user_id:
                await session.rollback()
                await self._fail(
                    claim,
                    conversation_id,
                    {
                        "category": "AUTHORITY",
                        "code": "TASK_OWNER_MISMATCH",
                        "message": "Task ownership is inconsistent",
                        "retryable": False,
                    },
                    policy=policy,
                )
                return
            user_id = task.user_id
            execution_principal = ExecutionPrincipal.for_task(user_id)
            runtime_backend = task.runtime_backend
            durable_executor_type = task.executor_type
            durable_executor_id = task.executor_id
            durable_requested_output = task.requested_output

        async def event_sink(event_type: str, data: dict[str, Any]) -> None:
            await self._persist_runtime_event(
                claim=claim,
                conversation_id=conversation_id,
                event_type=event_type,
                data=data,
            )

        try:
            decision = self._durable_route(
                executor_type=durable_executor_type,
                executor_id=durable_executor_id,
                requested_output=durable_requested_output,
            ) or await self._route(current_task)
            executor_id = (
                "planner:constrained"
                if decision.route is RequestRoute.COMPLEX_PLAN
                else "workflow:aa"
                if decision.route is RequestRoute.AA_COLLECTION
                else f"workflow:wealth-{decision.route.value.removeprefix('WEALTH_').lower()}"
                if decision.route in {RequestRoute.WEALTH_PURCHASE, RequestRoute.WEALTH_REDEEM}
                else TRANSFER_WORKFLOW_ID
                if decision.route is RequestRoute.TRANSFER_WORKFLOW
                else SUBSCRIPTION_RESUME_WORKFLOW_ID
                if decision.route is RequestRoute.SUBSCRIPTION_RESUME
                else SUBSCRIPTION_WORKFLOW_ID
                if decision.route is RequestRoute.SUBSCRIPTION_CANCEL
                else ROUTE_AGENT_IDS.get(decision.route)
            )
            if durable_executor_id is None:
                await self._persist_route(
                    claim=claim,
                    conversation_id=conversation_id,
                    route=decision.route,
                    executor_id=executor_id,
                    requested_output=decision.requested_output,
                )
            if decision.route is RequestRoute.COMPLEX_PLAN:
                await PlanExecutionService(self).execute(claim, current_task)
                return
            if decision.route is RequestRoute.UNSUPPORTED:
                await self._complete_without_agent(
                    claim=claim,
                    conversation_id=conversation_id,
                    answer=UNSUPPORTED_MESSAGE,
                    route=decision.route,
                )
                return
            if decision.route in {RequestRoute.WEALTH_PURCHASE, RequestRoute.WEALTH_REDEEM}:
                await self._run_wealth(
                    claim, conversation_id, user_id, current_task, decision.route
                )
                return
            if decision.route is RequestRoute.AA_COLLECTION:
                await self._run_aa(claim, conversation_id, user_id, current_task)
                return
            if decision.route is RequestRoute.TRANSFER_WORKFLOW:
                await self._run_transfer_workflow(
                    claim=claim,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    user_request=current_task,
                )
                return
            if decision.route in {
                RequestRoute.SUBSCRIPTION_CANCEL,
                RequestRoute.SUBSCRIPTION_RESUME,
            }:
                await self._run_subscription_workflow(
                    claim=claim,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    user_request=current_task,
                    resume=decision.route is RequestRoute.SUBSCRIPTION_RESUME,
                )
                return
            if executor_id is None:
                raise RoutingError("Route does not map to an executor")
            agent = self._get_agent(executor_id)
            if (
                decision.requested_output is RequestedOutput.MONTHLY_REPORT
                and agent.agent_id != FINANCIAL_ANALYSIS_AGENT_ID
            ):
                raise RoutingError("Monthly report requires FinancialAnalysisAgent")
            if (
                agent.agent_id in {FINANCIAL_ANALYSIS_AGENT_ID, "agent:wealth-advisor"}
                and runtime_backend is not RuntimeBackend.LANGGRAPH
            ):
                raise AgentRuntimeError(
                    "FINANCIAL_AGENT_REQUIRES_LANGGRAPH",
                    "FinancialAnalysisAgent requires LangGraph runtime",
                )
            runtime = self.runtime_factory.get(runtime_backend)
            run_agent = (
                self._report_source_agent(agent)
                if decision.requested_output is RequestedOutput.MONTHLY_REPORT
                else agent
            )
            if decision.requested_output is RequestedOutput.MONTHLY_REPORT:
                await self._update_progress(
                    claim=claim,
                    conversation_id=conversation_id,
                    message="正在分析消费数据",
                )
            result = await runtime.run(
                AgentRunRequest(
                    task_id=task_id,
                    conversation_id=conversation_id,
                    current_task=current_task,
                    conversation_messages=conversation_messages,
                    principal=execution_principal,
                    agent=run_agent,
                    event_sink=event_sink,
                )
            )
            if decision.requested_output is RequestedOutput.MONTHLY_REPORT:
                snapshot = build_financial_analysis_snapshot(result.state.successful_tool_results)
                if snapshot.spending_summary is None or snapshot.category_breakdown is None:
                    await self._complete_without_agent(
                        claim=claim,
                        conversation_id=conversation_id,
                        answer="未取得所选期间完整的账单汇总与分类数据，暂时无法生成报告。请核对年份、月份和账户范围后重试。",
                        route=decision.route,
                    )
                    return
                await self._run_report_pipeline(
                    claim=claim,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    agent_id=agent.agent_id,
                    snapshot=snapshot,
                    steps=result.state.step_count,
                    tool_calls=result.state.tool_call_count,
                )
                return
            async with self.session_factory() as session:
                tasks = TaskRepository(session)
                messages = MessageRepository(session)
                publisher = EventPublisher(session)
                task = await self._get_owned(tasks, claim, for_update=True)
                assistant = await messages.create(
                    conversation_id=conversation_id,
                    role=MessageRole.ASSISTANT,
                    content=subscription_answer(result.answer)
                    if agent.agent_id == SUBSCRIPTION_ANALYSIS_AGENT_ID
                    else result.answer,
                )
                await tasks.transition(
                    task,
                    TaskStatus.COMPLETED,
                    output=self._build_task_output(
                        agent_id=agent.agent_id,
                        assistant_message_id=str(assistant.message_id),
                        steps=result.state.step_count,
                        tool_calls=result.state.tool_call_count,
                        successful_tool_results=result.state.successful_tool_results,
                        requested_output=decision.requested_output,
                    ),
                )
                await publisher.persist(
                    event_type="task.completed",
                    conversation_id=conversation_id,
                    task_id=task_id,
                    data={
                        "status": task.status.value,
                        "version": task.version,
                        "runtime_backend": task.runtime_backend.value,
                        "checkpoint_enabled": runtime_backend is RuntimeBackend.LANGGRAPH,
                    },
                )
                await publisher.persist(
                    event_type="conversation.message.completed",
                    conversation_id=conversation_id,
                    task_id=task_id,
                    data={"message_id": str(assistant.message_id), "role": assistant.role.value},
                )
                await session.commit()
        except RoutingError:
            await self._fail(
                claim,
                conversation_id,
                {
                    "category": "INTERNAL",
                    "code": "ROUTING_FAILED",
                    "message": "Request routing failed",
                    "retryable": False,
                },
                policy=policy,
            )
        except TransferIntentExtractionError:
            await self._fail(
                claim,
                conversation_id,
                {
                    "category": "INPUT",
                    "code": "TRANSFER_INTENT_EXTRACTION_FAILED",
                    "message": "Transfer intent extraction failed",
                    "retryable": False,
                },
                policy=policy,
            )
        except SubscriptionCancelIntentExtractionError:
            await self._fail(
                claim,
                conversation_id,
                {
                    "category": "INPUT",
                    "code": "SUBSCRIPTION_INTENT_EXTRACTION_FAILED",
                    "message": "Subscription cancellation intent extraction failed",
                    "retryable": False,
                },
                policy=policy,
            )
        except PlanValidationError as exc:
            await self._fail(
                claim,
                conversation_id,
                {
                    "category": "PLAN",
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": False,
                },
                policy=policy,
            )
        except AgentRuntimeError as exc:
            await self._fail(claim, conversation_id, exc.as_dict(), policy=policy)
        except SkillExecutionError as exc:
            await self._fail(
                claim,
                conversation_id,
                {
                    "category": "INTERNAL",
                    "code": exc.code.value,
                    "message": exc.message,
                    "retryable": False,
                },
                policy=policy,
            )
        except ReportPersistenceError:
            await self._fail(
                claim,
                conversation_id,
                {
                    "category": "INTERNAL",
                    "code": "REPORT_PERSISTENCE_FAILED",
                    "message": "Report persistence failed",
                    "retryable": False,
                },
                policy=policy,
            )
        except (TaskLeaseLostError, asyncio.CancelledError):
            raise
        except Exception:
            error = {
                "category": "INTERNAL",
                "code": "AGENT_RUNTIME_ERROR",
                "message": "Agent runtime failed",
                "retryable": False,
            }
            await event_sink(
                "agent.run.failed",
                {"code": error["code"], "category": error["category"], "retryable": False},
            )
            await self._fail(claim, conversation_id, error, policy=policy)

    async def _route(self, current_task: str) -> RouteDecision:
        if self.router is None:
            return RouteDecision(
                route=RequestRoute.MINIMAL_BANKING,
                requested_output=RequestedOutput.ANSWER,
                confidence=1,
            )
        return await self.router.route(current_task)

    @staticmethod
    def _durable_route(
        *,
        executor_type: ExecutorType | None,
        executor_id: str | None,
        requested_output: RequestedOutput | None,
    ) -> RouteDecision | None:
        if executor_id is None or requested_output is None:
            return None
        if executor_id == "planner:constrained":
            route = RequestRoute.COMPLEX_PLAN
        elif executor_id in {"workflow:wealth-purchase", "workflow:wealth-redeem"}:
            route = (
                RequestRoute.WEALTH_PURCHASE
                if executor_id.endswith("purchase")
                else RequestRoute.WEALTH_REDEEM
            )
        elif executor_type is ExecutorType.WORKFLOW and executor_id in {
            "workflow:aa",
            TRANSFER_WORKFLOW_ID,
            SUBSCRIPTION_WORKFLOW_ID,
            SUBSCRIPTION_RESUME_WORKFLOW_ID,
        }:
            route = (
                RequestRoute.AA_COLLECTION
                if executor_id == "workflow:aa"
                else RequestRoute.TRANSFER_WORKFLOW
                if executor_id == TRANSFER_WORKFLOW_ID
                else RequestRoute.SUBSCRIPTION_RESUME
                if executor_id == SUBSCRIPTION_RESUME_WORKFLOW_ID
                else RequestRoute.SUBSCRIPTION_CANCEL
            )
        else:
            route = next(
                (
                    candidate
                    for candidate, agent_id in ROUTE_AGENT_IDS.items()
                    if agent_id == executor_id
                ),
                None,
            )
        if route is None:
            raise RoutingError("Persisted Task executor is not registered")
        return RouteDecision(
            route=route,
            requested_output=requested_output,
            confidence=1,
        )

    def _get_agent(self, agent_id: str) -> AgentDefinition:
        if self.agent_registry is None:
            if agent_id == MINIMAL_BANKING_AGENT.agent_id:
                return MINIMAL_BANKING_AGENT
            raise RoutingError("Agent registry is not configured")
        agent = self.agent_registry.get(agent_id)
        if agent is None:
            raise RoutingError("Routed agent is not registered")
        return agent

    async def _persist_route(
        self,
        *,
        claim: TaskExecutionClaim,
        conversation_id: UUID,
        route: RequestRoute,
        executor_id: str | None,
        requested_output: RequestedOutput,
    ) -> None:
        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            publisher = EventPublisher(session)
            task = await self._get_owned(tasks, claim, for_update=True)
            executor_type = None
            if route in {
                RequestRoute.TRANSFER_WORKFLOW,
                RequestRoute.WEALTH_PURCHASE,
                RequestRoute.WEALTH_REDEEM,
                RequestRoute.AA_COLLECTION,
                RequestRoute.SUBSCRIPTION_CANCEL,
                RequestRoute.SUBSCRIPTION_RESUME,
            }:
                executor_type = ExecutorType.WORKFLOW
            elif executor_id is not None and route is not RequestRoute.COMPLEX_PLAN:
                executor_type = ExecutorType.AGENT
            await tasks.assign_route(
                task,
                requested_output=requested_output,
                executor_type=executor_type,
                executor_id=executor_id,
            )
            await publisher.persist(
                event_type="request.routed",
                conversation_id=conversation_id,
                task_id=claim.task_id,
                data={
                    "route": route.value,
                    "requested_output": requested_output.value,
                    "executor_id": executor_id,
                },
            )
            await session.commit()

    async def _run_wealth(self, claim, conversation_id, user_id, request, route):
        from banking_api.wealth.catalog import PRODUCTS
        from banking_api.wealth.intent import extract_quantity
        from banking_api.wealth.workflow import wealth_workflow

        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            task = await self._get_owned(tasks, claim, for_update=True)
            direction = route.value.removeprefix("WEALTH_")
            matches = [
                f"mock-wealth-{i:02}"
                for i, p in enumerate(PRODUCTS, 1)
                if p[0] in request or p[0].removeprefix("演示") in request
            ]
            accounts = self.transfer_workflow_engine.wealth_engine.balances._bank.list_accounts(
                user_id=user_id
            )
            selected = [a["account_id"] for a in accounts if a["display_name"] in request]
            numeric = extract_quantity(request, direction)
            draft = {
                "direction": direction,
                "product_id": matches[0] if len(matches) == 1 else None,
                "account_id": selected[0] if len(selected) == 1 else None,
                "quantity": numeric.quantity,
                "quantity_unit": numeric.unit,
                "redeem_all": numeric.redeem_all,
                "quantity_message": numeric.message,
            }
            workflow = await wealth_workflow(
                direction, session, self.transfer_workflow_engine.wealth_engine.balances
            ).create(user_id, conversation_id, claim.task_id, draft, allow_invalid_draft=True)
            await tasks.transition(
                task,
                TaskStatus.WAITING_USER,
                output={
                    "route": route.value,
                    "workflow_id": str(workflow.workflow_id),
                    "requested_output": "WORKFLOW",
                },
            )
            await EventPublisher(session).persist(
                event_type="task.waiting_user",
                conversation_id=conversation_id,
                task_id=claim.task_id,
                data={"status": task.status.value, "version": task.version},
            )
            await session.commit()

    async def _run_transfer_workflow(
        self,
        *,
        claim: TaskExecutionClaim,
        conversation_id: UUID,
        user_id: str,
        user_request: str,
    ) -> None:
        if self.transfer_intent_extractor is None or self.transfer_workflow_engine is None:
            raise AgentRuntimeError(
                "TRANSFER_WORKFLOW_NOT_CONFIGURED",
                "Transfer workflow is not configured",
            )
        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            await self._get_owned(tasks, claim)
            workflow_service = WorkflowService(session, self.bus, self.transfer_workflow_engine)
            workflow = await workflow_service.get_by_source_task(claim.task_id, user_id=user_id)

        if workflow is None:
            intent = await self.transfer_intent_extractor.extract(user_request)
            async with self.session_factory() as session:
                tasks = TaskRepository(session)
                await self._get_owned(tasks, claim, for_update=True)
                workflow_service = WorkflowService(session, self.bus, self.transfer_workflow_engine)
                workflow = await workflow_service.get_by_source_task(claim.task_id, user_id=user_id)
                if workflow is None:
                    workflow = await workflow_service.create_transfer(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        source_task_id=claim.task_id,
                        intent=intent,
                    )

        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            messages = MessageRepository(session)
            publisher = EventPublisher(session)
            task = await self._get_owned(tasks, claim, for_update=True)
            assistant = await messages.create(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content="转账流程已建立，请在转账卡片中选择或核对资料，并查看最终执行状态。",
            )
            await tasks.transition(
                task,
                TaskStatus.COMPLETED,
                output={
                    "route": RequestRoute.TRANSFER_WORKFLOW.value,
                    "requested_output": RequestedOutput.WORKFLOW.value,
                    "workflow_id": str(workflow.workflow_id),
                    "assistant_message_id": str(assistant.message_id),
                },
            )
            await publisher.persist(
                event_type="task.completed",
                conversation_id=conversation_id,
                task_id=claim.task_id,
                data={"status": task.status.value, "version": task.version},
            )
            await publisher.persist(
                event_type="conversation.message.completed",
                conversation_id=conversation_id,
                task_id=claim.task_id,
                data={"message_id": str(assistant.message_id), "role": assistant.role.value},
            )
            await session.commit()

    async def _complete_without_agent(
        self,
        *,
        claim: TaskExecutionClaim,
        conversation_id: UUID,
        answer: str,
        route: RequestRoute,
    ) -> None:
        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            messages = MessageRepository(session)
            publisher = EventPublisher(session)
            task = await self._get_owned(tasks, claim, for_update=True)
            assistant = await messages.create(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=answer,
            )
            await tasks.transition(
                task,
                TaskStatus.COMPLETED,
                output={
                    "agent_id": None,
                    "route": route.value,
                    "requested_output": RequestedOutput.ANSWER.value,
                    "assistant_message_id": str(assistant.message_id),
                },
            )
            await publisher.persist(
                event_type="task.completed",
                conversation_id=conversation_id,
                task_id=claim.task_id,
                data={
                    "status": task.status.value,
                    "version": task.version,
                    "runtime_backend": task.runtime_backend.value,
                    "checkpoint_enabled": False,
                },
            )
            await publisher.persist(
                event_type="conversation.message.completed",
                conversation_id=conversation_id,
                task_id=claim.task_id,
                data={"message_id": str(assistant.message_id), "role": assistant.role.value},
            )
            await session.commit()

    async def _run_subscription_workflow(
        self,
        *,
        claim: TaskExecutionClaim,
        conversation_id: UUID,
        user_id: str,
        user_request: str,
        resume: bool = False,
    ) -> None:
        if (
            self.subscription_intent_extractor is None
            or self.subscription_workflow_engine is None
            or self.transfer_workflow_engine is None
        ):
            raise AgentRuntimeError(
                "SUBSCRIPTION_WORKFLOW_NOT_CONFIGURED",
                "Subscription cancellation workflow is not configured",
            )
        async with self.session_factory() as session:
            service = WorkflowService(
                session,
                self.bus,
                self.transfer_workflow_engine,
                subscription_engine=self.subscription_workflow_engine,
            )
            workflow = await service.get_by_source_task(claim.task_id, user_id=user_id)
        if workflow is None:
            intent = await self.subscription_intent_extractor.extract(user_request)
            async with self.session_factory() as session:
                tasks = TaskRepository(session)
                await self._get_owned(tasks, claim, for_update=True)
                service = WorkflowService(
                    session,
                    self.bus,
                    self.transfer_workflow_engine,
                    subscription_engine=self.subscription_workflow_engine,
                )
                workflow = await service.get_by_source_task(claim.task_id, user_id=user_id)
                if workflow is None:
                    workflow = await service.create_subscription_cancel(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        source_task_id=claim.task_id,
                        intent=intent,
                        resume=resume,
                    )
        state = workflow.state
        message = (
            str(state.get("error_message"))
            if workflow.status is WorkflowStatus.FAILED and state.get("error_message")
            else "找到多个订阅，请在业务卡片中明确选择。"
            if workflow.status is WorkflowStatus.WAITING_FOR_INPUT
            else "恢复订阅流程已建立，请在业务卡片中核对套餐、下次扣费时间及最终执行状态。"
            if resume
            else "取消订阅流程已建立，请在业务卡片中核对订阅及最终执行状态。"
        )
        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            messages = MessageRepository(session)
            publisher = EventPublisher(session)
            task = await self._get_owned(tasks, claim, for_update=True)
            assistant = await messages.create(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=subscription_answer(message),
            )
            await tasks.transition(
                task,
                TaskStatus.COMPLETED,
                output={
                    "route": (
                        RequestRoute.SUBSCRIPTION_RESUME
                        if resume
                        else RequestRoute.SUBSCRIPTION_CANCEL
                    ).value,
                    "requested_output": RequestedOutput.WORKFLOW.value,
                    "workflow_id": str(workflow.workflow_id),
                    "assistant_message_id": str(assistant.message_id),
                },
            )
            await publisher.persist(
                event_type="task.completed",
                conversation_id=conversation_id,
                task_id=claim.task_id,
                data={"status": task.status.value, "version": task.version},
            )
            await publisher.persist(
                event_type="conversation.message.completed",
                conversation_id=conversation_id,
                task_id=claim.task_id,
                data={"message_id": str(assistant.message_id), "role": assistant.role.value},
            )
            await session.commit()

    @staticmethod
    def _build_task_output(
        *,
        agent_id: str,
        assistant_message_id: str,
        steps: int,
        tool_calls: int,
        successful_tool_results: list[SuccessfulToolResult],
        requested_output: RequestedOutput,
    ) -> dict[str, Any]:
        output: dict[str, Any] = {
            "agent_id": agent_id,
            "assistant_message_id": assistant_message_id,
            "steps": steps,
            "tool_calls": tool_calls,
            "requested_output": requested_output.value,
        }
        if agent_id == MINIMAL_BANKING_AGENT.agent_id:
            output["account_results"] = [
                result.model_dump(mode="json")
                for result in build_account_results(successful_tool_results)
            ]
        if agent_id == FINANCIAL_ANALYSIS_AGENT_ID:
            snapshot = build_financial_analysis_snapshot(successful_tool_results)
            output["analysis_snapshot"] = snapshot.model_dump(mode="json")
            anomaly_result = next(
                (
                    item
                    for item in successful_tool_results
                    if item.capability_id == "transaction.detect_anomalies"
                ),
                None,
            )
            if anomaly_result is not None and "snapshot" in anomaly_result.output:
                output["transaction_anomaly_snapshot"] = anomaly_result.output["snapshot"]
                from banking_api.financial.anomaly_models import TransactionAnomalySnapshot
                from banking_api.skills.transaction_anomaly_analysis import (
                    TransactionAnomalyAnalysisSkill,
                )

                output["transaction_anomaly_answer"] = (
                    TransactionAnomalyAnalysisSkill()
                    .execute(
                        TransactionAnomalySnapshot.model_validate(anomaly_result.output["snapshot"])
                    )
                    .answer
                )
                output["anomaly_skill_id"] = "skill:transaction-anomaly-analysis"
                output["anomaly_skill_version"] = 1
                if snapshot.spending_summary is not None:
                    output["anomaly_presentation"] = "combined"
                    output.pop("transaction_anomaly_answer", None)
        if agent_id == MINIMAL_BANKING_AGENT.agent_id:
            payees = [
                item.output
                for item in successful_tool_results
                if item.capability_id in {"payee.list", "payee.search"}
            ]
            if payees:
                output["payee_results"] = payees
        if agent_id == SUBSCRIPTION_ANALYSIS_AGENT_ID:
            result = next(
                (
                    item
                    for item in successful_tool_results
                    if item.capability_id == "subscription.analyze"
                ),
                None,
            )
            if result is not None and "snapshot" in result.output:
                output["subscription_analysis_snapshot"] = result.output["snapshot"]
        if agent_id == "agent:wealth-advisor":
            from banking_api.wealth.schemas import WealthReadResult

            output["wealth_results"] = [
                WealthReadResult.model_validate(item.output).model_dump(mode="json")
                for item in successful_tool_results
                if item.capability_id.startswith("wealth.")
            ]
        return output

    @staticmethod
    def _report_source_agent(agent: AgentDefinition) -> AgentDefinition:
        return AgentDefinition(
            agent_id=agent.agent_id,
            instructions=f"{agent.instructions}\n\n{REPORT_SOURCE_INSTRUCTIONS}",
            allowed_capabilities=agent.allowed_capabilities,
        )

    async def _run_report_pipeline(
        self,
        *,
        claim: TaskExecutionClaim,
        conversation_id: UUID,
        user_id: str,
        agent_id: str,
        snapshot: FinancialAnalysisSnapshot,
        steps: int,
        tool_calls: int,
    ) -> None:
        if self.skill_registry is None or self.skill_executor is None:
            raise SkillExecutionError(
                code=SkillErrorCode.REPORT_INPUT_INCOMPLETE,
                message="Monthly report skill runtime is not configured",
            )
        definition = self.skill_registry.get(MONTHLY_SPENDING_REPORT_SKILL_ID)
        if definition is None:
            raise SkillExecutionError(
                code=SkillErrorCode.REPORT_INPUT_INCOMPLETE,
                message="Monthly report skill is not registered",
            )
        await self._update_progress(
            claim=claim,
            conversation_id=conversation_id,
            message="正在生成报告",
        )
        await self._persist_skill_event(
            claim=claim,
            conversation_id=conversation_id,
            event_type="skill.run.started",
            skill_id=definition.skill_id,
            skill_version=definition.version,
        )
        try:
            report = await self.skill_executor.execute_registered(definition, snapshot)
        except SkillExecutionError:
            await self._persist_skill_event(
                claim=claim,
                conversation_id=conversation_id,
                event_type="skill.run.failed",
                skill_id=definition.skill_id,
                skill_version=definition.version,
            )
            raise
        await self._persist_skill_event(
            claim=claim,
            conversation_id=conversation_id,
            event_type="skill.run.completed",
            skill_id=definition.skill_id,
            skill_version=definition.version,
        )
        await self._update_progress(
            claim=claim,
            conversation_id=conversation_id,
            message="正在保存报告",
        )
        await self._persist_report_completion(
            claim=claim,
            conversation_id=conversation_id,
            user_id=user_id,
            agent_id=agent_id,
            snapshot=snapshot,
            report=report,
            skill=definition,
            steps=steps,
            tool_calls=tool_calls,
        )

    async def _persist_report_completion(
        self,
        *,
        claim: TaskExecutionClaim,
        conversation_id: UUID,
        user_id: str,
        agent_id: str,
        snapshot: FinancialAnalysisSnapshot,
        report: MonthlySpendingReport,
        skill: SkillDefinition,
        steps: int,
        tool_calls: int,
    ) -> None:
        try:
            async with self.session_factory() as session:
                tasks = TaskRepository(session)
                messages = MessageRepository(session)
                publisher = EventPublisher(session)
                task = await self._get_owned(tasks, claim, for_update=True)
                artifact = await ReportService(session).create_report(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    source_task_id=claim.task_id,
                    report=report,
                    snapshot=snapshot,
                    skill=skill,
                )
                await publisher.persist(
                    event_type="report.generated",
                    conversation_id=conversation_id,
                    task_id=claim.task_id,
                    data={
                        "report_id": str(artifact.report_id),
                        "report_type": artifact.report_type.value,
                        "period": artifact.period,
                        "source_task_id": str(claim.task_id),
                    },
                )
                parts = artifact.period.split("-")
                period_label = (
                    f"{parts[0]}年{int(parts[1])}月" if len(parts) == 2 else f"{parts[0]}年年度"
                )
                assistant = await messages.create(
                    conversation_id=conversation_id,
                    role=MessageRole.ASSISTANT,
                    content=f"{period_label}消费报告已生成。",
                )
                await tasks.transition(
                    task,
                    TaskStatus.COMPLETED,
                    output={
                        "requested_output": RequestedOutput.MONTHLY_REPORT.value,
                        "agent_id": agent_id,
                        "analysis_snapshot": snapshot.model_dump(mode="json"),
                        "skill_id": skill.skill_id,
                        "skill_version": skill.version,
                        "report_id": str(artifact.report_id),
                        "report_type": ReportType.MONTHLY_SPENDING.value,
                        "assistant_message_id": str(assistant.message_id),
                        "steps": steps,
                        "tool_calls": tool_calls,
                    },
                )
                await publisher.persist(
                    event_type="task.completed",
                    conversation_id=conversation_id,
                    task_id=claim.task_id,
                    data={
                        "status": task.status.value,
                        "version": task.version,
                        "runtime_backend": task.runtime_backend.value,
                        "checkpoint_enabled": (task.runtime_backend is RuntimeBackend.LANGGRAPH),
                    },
                )
                await publisher.persist(
                    event_type="conversation.message.completed",
                    conversation_id=conversation_id,
                    task_id=claim.task_id,
                    data={
                        "message_id": str(assistant.message_id),
                        "role": assistant.role.value,
                    },
                )
                await session.commit()
        except ReportPersistenceError:
            raise
        except Exception as exc:
            raise ReportPersistenceError("Report persistence failed") from exc

    async def _persist_skill_event(
        self,
        *,
        claim: TaskExecutionClaim,
        conversation_id: UUID,
        event_type: str,
        skill_id: str,
        skill_version: int,
    ) -> None:
        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            await self._get_owned(tasks, claim, for_update=True)
            publisher = EventPublisher(session)
            await publisher.persist(
                event_type=event_type,
                conversation_id=conversation_id,
                task_id=claim.task_id,
                data={
                    "skill_id": skill_id,
                    "skill_version": skill_version,
                    "task_id": str(claim.task_id),
                },
            )
            await session.commit()

    async def _update_progress(
        self,
        *,
        claim: TaskExecutionClaim,
        conversation_id: UUID,
        message: str,
    ) -> None:
        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            publisher = EventPublisher(session)
            task = await self._get_owned(tasks, claim, for_update=True)
            if task.progress_message == message:
                return
            await tasks.update_progress(task, message)
            await publisher.persist(
                event_type="task.progress",
                conversation_id=conversation_id,
                task_id=claim.task_id,
                data={"message": message, "version": task.version},
            )
            await session.commit()

    async def _persist_runtime_event(
        self,
        *,
        claim: TaskExecutionClaim,
        conversation_id: UUID,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        progress_message = None
        if event_type == "tool.call.started":
            progress_message = "正在查询账户"
        elif event_type == "tool.call.completed":
            progress_message = "正在整理结果"

        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            publisher = EventPublisher(session)
            persisted = []
            task = await self._get_owned(tasks, claim, for_update=True)
            if progress_message is not None and task.progress_message != progress_message:
                await tasks.update_progress(task, progress_message)
                persisted.append(
                    await publisher.persist(
                        event_type="task.progress",
                        conversation_id=conversation_id,
                        task_id=claim.task_id,
                        data={"message": progress_message, "version": task.version},
                    )
                )
            persisted.append(
                await publisher.persist(
                    event_type=event_type,
                    conversation_id=conversation_id,
                    task_id=claim.task_id,
                    data=data,
                )
            )
            await session.commit()

    async def _fail(
        self,
        claim: TaskExecutionClaim,
        conversation_id: UUID,
        error: dict[str, Any],
        *,
        policy: TaskExecutionPolicy,
    ) -> None:
        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            publisher = EventPublisher(session)
            task = await self._get_owned(tasks, claim, for_update=True)
            retryable = error.get("retryable") is True
            if retryable:
                next_run_at = self.clock() + policy.retry_delay(claim.attempt)
                await tasks.schedule_retry(
                    task,
                    error=error,
                    next_run_at=next_run_at,
                )
                event_type = "task.interrupted"
                logger.info(
                    "task retry scheduled task_id=%s attempt=%s code=%s next_run_at=%s",
                    claim.task_id,
                    claim.attempt,
                    error.get("code"),
                    next_run_at,
                )
            else:
                next_run_at = None
                await fail_plan(session, claim.task_id, error["code"])
                await tasks.transition(task, TaskStatus.FAILED, error=error)
                event_type = "task.failed"
                logger.info(
                    "task terminal failure task_id=%s attempt=%s code=%s",
                    claim.task_id,
                    claim.attempt,
                    error.get("code"),
                )
            await publisher.persist(
                event_type=event_type,
                conversation_id=conversation_id,
                task_id=claim.task_id,
                data={
                    "status": task.status.value,
                    "version": task.version,
                    "code": error["code"],
                    "runtime_backend": task.runtime_backend.value,
                    "checkpoint_enabled": task.runtime_backend is RuntimeBackend.LANGGRAPH,
                    "retryable": retryable,
                    "next_run_at": (next_run_at.isoformat() if next_run_at is not None else None),
                },
            )
            await session.commit()

    async def _get_owned(
        self,
        tasks: TaskRepository,
        claim: TaskExecutionClaim,
        *,
        for_update: bool = False,
    ):  # type: ignore[no-untyped-def]
        task = await tasks.get_owned(
            task_id=claim.task_id,
            lease_owner=claim.lease_owner,
            attempt=claim.attempt,
            now=self.clock(),
            for_update=for_update,
        )
        if task is None:
            raise TaskLeaseLostError
        return task

    async def _run_aa(self, claim, conversation_id, user_id, user_request):
        from banking_api.application.aa_service import AAService

        if self.aa_intent_extractor is None or self.aa_bank is None:
            raise AgentRuntimeError("AA_NOT_CONFIGURED", "AA collection is not configured")
        async with self.session_factory() as session:
            task = await self._get_owned(TaskRepository(session), claim)
            from sqlalchemy import select

            from banking_api.persistence.models import AARequestModel

            existing = await session.scalar(
                select(AARequestModel).where(
                    AARequestModel.source_task_id == claim.task_id,
                    AARequestModel.user_id == user_id,
                )
            )
        intent = None if existing else await self.aa_intent_extractor.extract(user_request)
        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            task = await self._get_owned(tasks, claim, for_update=True)
            service = AAService(session, self.bus, self.transfer_workflow_engine, self.aa_bank)
            request = (
                await service.get(existing.request_id, user_id)
                if existing
                else await service.create(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    source_task_id=claim.task_id,
                    intent=intent,
                )
            )
            await self._get_owned(tasks, claim, for_update=True)
            message = await MessageRepository(session).create(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=(
                    "AA 收款草稿已建立。请核对参与者、分摊金额与收款账户，再确认发布；"
                    "每位参与者需要以自己的身份独立授权付款。"
                ),
            )
            await tasks.transition(
                task,
                TaskStatus.COMPLETED,
                output={
                    "route": "AA_COLLECTION",
                    "requested_output": "WORKFLOW",
                    "aa_request_id": request["request_id"],
                    "assistant_message_id": str(message.message_id),
                },
            )
            await EventPublisher(session).persist(
                event_type="task.completed",
                conversation_id=conversation_id,
                task_id=claim.task_id,
                data={"aa_request_id": request["request_id"]},
            )
            await session.commit()
