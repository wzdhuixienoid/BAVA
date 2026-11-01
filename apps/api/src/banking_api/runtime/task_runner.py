import asyncio
import logging
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from banking_api.agent_skills import ActivatedSkill, SkillSelectionError, packaged_catalog
from banking_api.agents.models import AgentDefinition
from banking_api.agents.personal_banking_agent import (
    LEGACY_AGENT_ROUTES,
    PERSONAL_BANKING_ACCOUNT_AGENT,
    PERSONAL_BANKING_AGENT,
    PERSONAL_BANKING_AGENT_ID,
    PersonalBankingMode,
    personal_banking_agent,
    uses_financial_analysis,
)
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
    RequestRoute.ACCOUNT_QUERY: PERSONAL_BANKING_ACCOUNT_AGENT.agent_id,
    RequestRoute.FINANCIAL_ANALYSIS: PERSONAL_BANKING_AGENT_ID,
    RequestRoute.PERSONAL_BANKING: PERSONAL_BANKING_AGENT_ID,
    RequestRoute.SUBSCRIPTION_ANALYSIS: SUBSCRIPTION_ANALYSIS_AGENT_ID,
}
TRANSFER_WORKFLOW_ID = "workflow:transfer"
SUBSCRIPTION_WORKFLOW_ID = "workflow:subscription-cancel"
SUBSCRIPTION_RESUME_WORKFLOW_ID = "workflow:subscription-resume"


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
        wealth_clock=None,
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
        from banking_api.config.demo_time import reference_now

        self.wealth_clock = wealth_clock or reference_now

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
            wealth_before = task.created_at
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
            saved_wealth_intent = task.input_json.get("wealth_intent")
            durable_banking_route = task.input_json.get("personal_banking_route")

        async def event_sink(event_type: str, data: dict[str, Any]) -> None:
            await self._persist_runtime_event(
                claim=claim,
                conversation_id=conversation_id,
                event_type=event_type,
                data=data,
            )

        try:
            from banking_api.application.statement_results import (
                continuation_context,
                is_statement_continuation,
            )

            statement_context = None
            if is_statement_continuation(current_task):
                async with self.session_factory() as statement_session:
                    statement_context = await continuation_context(
                        statement_session,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        before=wealth_before,
                    )
                if statement_context is not None and statement_context["next_offset"] is None:
                    await self._complete_without_agent(
                        claim=claim,
                        conversation_id=conversation_id,
                        answer="所选条件下的账单已显示完毕，没有更多已入账记录。",
                        route=RequestRoute.ACCOUNT_QUERY,
                    )
                    return
            from banking_api.wealth.context import (
                ASSESSMENT_UPDATE,
                concise_context,
                latest_analysis,
                latest_purchase_interest,
                trade_reference,
            )

            async with self.session_factory() as snapshot_session:
                previous_wealth = await latest_analysis(
                    snapshot_session, user_id, conversation_id, before=wealth_before
                )
                prior_purchase = (
                    await latest_purchase_interest(
                        snapshot_session, user_id, conversation_id, before=wealth_before
                    )
                    if ASSESSMENT_UPDATE.search(current_task) and previous_wealth is None
                    else None
                )
            from banking_api.wealth.quantity_parser import quantities

            money_goal = bool(
                quantities(current_task)
                and re.search(r"收益|赚钱|亏损|投资|本金|推荐", current_task)
            )
            wealth_frame = None
            wealth_body = None
            if (
                self.router
                and self.transfer_workflow_engine
                and (
                    (
                        previous_wealth
                        and re.search(
                            r"定位|策略|产品|开放|到账|拿钱|预算|投资|收益|赚钱|亏|损失|稳健|保守|进取|均衡|第一|第二|这款|这个|上次|为什么|用钱|期限|卡|账户|买|比较|费|\d|千|万",
                            current_task,
                        )
                    )
                    or money_goal
                    or re.search(
                        r"理财|申购|赎回|测评|回撤|净值|保本|本金|每天开放|演示(?:稳|均衡|进取|高波动)|产品.{0,12}(?:定位|投资策略|收益来源)|(?:预算|投资).*(?:收益|赚钱|亏损|本金|产品)|(?:收益|赚钱|亏损).*(?:预算|产品)|(?:有|投入|投)[^。]{0,20}(?:千|万|元|块|[kK])[^。]{0,30}(?:收益|亏损|投资)",
                        current_task,
                    )
                )
                and not re.search(r"转账|订阅|消费|账单", current_task)
                and not RequestRouter._is_statement_query(current_task)
            ):
                from banking_api.wealth.coordination import analysis_request
                from banking_api.wealth.semantic import WealthIntentFrame, interpret
                from banking_api.wealth.service import WealthService

                wealth_frame = (
                    WealthIntentFrame.model_validate(saved_wealth_intent)
                    if saved_wealth_intent
                    else await interpret(self.router._provider, current_task, previous_wealth)
                )
                wealth_frame.source_message_id = str(message_id)
                async with self.session_factory() as frame_session:
                    svc = WealthService(
                        frame_session,
                        self.transfer_workflow_engine.wealth_engine.balances,
                        self.wealth_clock,
                    )
                    wealth_body = analysis_request(
                        wealth_frame,
                        await svc.products(user_id),
                        previous_wealth,
                        svc.balances._bank.list_accounts(user_id=user_id),
                    )
                    if ASSESSMENT_UPDATE.search(current_task) and (
                        previous_wealth or prior_purchase
                    ):
                        from banking_api.wealth.context import analysis_input

                        remembered = prior_purchase or (
                            previous_wealth.intent_frame.source_text
                            if previous_wealth.intent_frame
                            else previous_wealth.needs.raw
                        )
                        resumed = analysis_input(
                            remembered, await svc.products(user_id), previous_wealth
                        )
                        wealth_body.product_ids = resumed.product_ids
                        wealth_body.intent = (
                            "PRODUCT_INTRO" if resumed.product_ids else "RECOMMENDATION"
                        )
                        wealth_frame.action = "RECOMMEND"
                        wealth_frame.ambiguities = []
                    task = await self._get_owned(
                        TaskRepository(frame_session), claim, for_update=True
                    )
                    task.input_json = dict(task.input_json) | {
                        "wealth_intent": wealth_frame.model_dump(mode="json")
                    }
                    await frame_session.commit()
            workflow_task = (
                current_task if wealth_frame else trade_reference(current_task, previous_wealth)
            )

            if workflow_task is None:
                await self._complete_without_agent(
                    claim=claim,
                    conversation_id=conversation_id,
                    answer="产品指代不唯一或没有对应候选，请先明确产品名称；不会创建交易。",
                    route=RequestRoute.WEALTH_ANALYSIS,
                )
                return
            # A hypothetical fee/suitability question is read-only; it does not authorize
            # conditional execution. Explicit automatic/multiple writes remain unsupported.
            readonly_hypothesis = bool(
                re.search(r"费用|手续费|费率|成本|到账|适合|风险", current_task)
                and not re.search(r"帮我买|替我买|自动|就买|则买|提交|下单", current_task)
            )
            unsupported_wealth = bool(
                re.search(r"自动|定投|调仓|分别买|各买|多笔", current_task)
                or (re.search(r"如果.*(?:买|申购|赎回)", current_task) and not readonly_hypothesis)
            )
            decision = self._durable_route(
                executor_type=durable_executor_type,
                executor_id=durable_executor_id,
                requested_output=durable_requested_output,
                personal_banking_route=durable_banking_route,
            )
            if decision is None:
                if statement_context:
                    decision = RouteDecision(
                        route=RequestRoute.ACCOUNT_QUERY,
                        requested_output=RequestedOutput.ANSWER,
                        confidence=1,
                    )
                elif (
                    wealth_frame
                    and wealth_frame.action != "ORDER_STATUS"
                    and not unsupported_wealth
                ):
                    decision = RouteDecision(
                        route=RequestRoute.WEALTH_ANALYSIS,
                        requested_output=RequestedOutput.ANSWER,
                        confidence=1,
                    )
                else:
                    decision = await self._route(
                        workflow_task, concise_context(previous_wealth) if previous_wealth else None
                    )
            if wealth_frame and wealth_frame.action != "ORDER_STATUS" and not unsupported_wealth:
                from banking_api.wealth.needs import collect_needs

                current_needs = collect_needs(
                    wealth_body,
                    self.wealth_clock(),
                    previous_wealth.needs if previous_wealth else None,
                )
                complete_purchase = (
                    wealth_frame.action == "PREPARE_PURCHASE"
                    and not wealth_frame.ambiguities
                    and not current_needs.constraints.no_principal_loss
                    and not current_needs.constraints.principal_guarantee
                    and len(wealth_body.product_ids) == 1
                    and (
                        wealth_body.account_id
                        or (previous_wealth and previous_wealth.needs.account_id)
                    )
                    and (wealth_body.amount or (previous_wealth and previous_wealth.needs.amount))
                )
                decision = RouteDecision(
                    route=RequestRoute.WEALTH_PURCHASE
                    if complete_purchase
                    else RequestRoute.WEALTH_REDEEM
                    if wealth_frame.action == "PREPARE_REDEEM" and not wealth_frame.ambiguities
                    else RequestRoute.WEALTH_ANALYSIS,
                    requested_output=RequestedOutput.WORKFLOW
                    if complete_purchase
                    or wealth_frame.action == "PREPARE_REDEEM"
                    and not wealth_frame.ambiguities
                    else RequestedOutput.ANSWER,
                    confidence=1,
                )
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
                    claim,
                    conversation_id,
                    user_id,
                    workflow_task,
                    decision.route,
                    body=wealth_body,
                    previous=previous_wealth,
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
            if agent.agent_id == PERSONAL_BANKING_AGENT_ID:
                agent = personal_banking_agent(
                    {
                        RequestRoute.ACCOUNT_QUERY: PersonalBankingMode.ACCOUNT,
                        RequestRoute.FINANCIAL_ANALYSIS: PersonalBankingMode.SPENDING,
                        RequestRoute.PERSONAL_BANKING: PersonalBankingMode.COMBINED,
                    }[decision.route],
                    report=decision.requested_output is RequestedOutput.MONTHLY_REPORT,
                )
            if (
                decision.requested_output is RequestedOutput.MONTHLY_REPORT
                and not uses_financial_analysis(agent)
            ):
                raise RoutingError("Monthly report requires the spending skill")
            if (
                uses_financial_analysis(agent) or agent.agent_id == "agent:wealth-advisor"
            ) and runtime_backend is not RuntimeBackend.LANGGRAPH:
                raise AgentRuntimeError(
                    "FINANCIAL_AGENT_REQUIRES_LANGGRAPH",
                    "Spending analysis requires LangGraph runtime",
                )
            run_agent = agent
            if decision.requested_output is RequestedOutput.MONTHLY_REPORT:
                await self._update_progress(
                    claim=claim,
                    conversation_id=conversation_id,
                    message="正在分析消费数据",
                )
            wealth_analysis = None
            wealth_context = concise_context(previous_wealth) if previous_wealth else None
            if (
                agent.agent_id == "agent:wealth-advisor"
                and self.transfer_workflow_engine
                and not any(w in current_task for w in ("持仓", "订单"))
            ):
                from banking_api.wealth.advisory import WealthAdvisoryService
                from banking_api.wealth.answer import answer_prompt
                from banking_api.wealth.context import analysis_input
                from banking_api.wealth.service import WealthService

                async with self.session_factory() as analysis_session:
                    balances = self.transfer_workflow_engine.wealth_engine.balances
                    svc = WealthService(analysis_session, balances, self.wealth_clock)
                    body = wealth_body or analysis_input(
                        (prior_purchase + "；" + current_task) if prior_purchase else workflow_task,
                        await svc.products(user_id),
                        previous_wealth,
                    )
                    body.query = current_task
                    wealth_analysis = await WealthAdvisoryService(svc).analyze(
                        user_id, body, previous_wealth
                    )
                    wealth_analysis.source_task_id = task_id
                    wealth_analysis.snapshot_id = task_id
                    from uuid import NAMESPACE_URL, uuid5

                    for candidate in wealth_analysis.candidates:
                        candidate.purchase_entry_key = uuid5(
                            NAMESPACE_URL,
                            f"{task_id}:{candidate.product.product_id}:purchase-entry",
                        )
                active_skill = packaged_catalog().activate(
                    wealth_frame.action if wealth_frame else "RECOMMEND", current_task
                )
                await event_sink("agent_skill.activated", active_skill.metadata())
                run_agent = AgentDefinition(
                    agent_id=agent.agent_id,
                    allowed_capabilities=agent.allowed_capabilities,
                    instructions=answer_prompt(wealth_analysis, active_skill),
                    skills=(active_skill,),
                )
            try:
                runtime = self.runtime_factory.get(runtime_backend)
                result = await runtime.run(
                    AgentRunRequest(
                        task_id=task_id,
                        conversation_id=conversation_id,
                        current_task=current_task,
                        conversation_messages=conversation_messages
                        if wealth_analysis is None
                        else [],
                        principal=execution_principal,
                        agent=run_agent,
                        event_sink=event_sink,
                        wealth_context=wealth_context,
                        statement_context=statement_context,
                        initial_tool_calls=__import__(
                            "banking_api.wealth.answer", fromlist=["initial_fact_calls"]
                        ).initial_fact_calls(wealth_analysis)
                        if wealth_analysis
                        else (),
                    )
                )
            except Exception as exc:
                if wealth_analysis is None:
                    raise
                from banking_api.runtime.base import AgentRunResult, AgentRunState

                wealth_analysis.degradation_reason = (
                    "说明整理暂不可用，已使用相同事实与资料的基础分析。"
                )
                result = AgentRunResult(answer="", state=AgentRunState(task_id, conversation_id))
                logger.info("Wealth narrative unavailable: %s", type(exc).__name__)
            if wealth_analysis is not None:
                from banking_api.runtime.base import AgentRunResult
                from banking_api.wealth.answer import answer_prompt, apply_answer

                wealth_analysis = apply_answer(wealth_analysis, result.answer, active_skill)
                if wealth_analysis.narrative_source == "DETERMINISTIC_FALLBACK" and result.answer:
                    try:
                        repaired = await runtime.run(
                            AgentRunRequest(
                                task_id=task_id,
                                conversation_id=conversation_id,
                                current_task="修复答复契约（最多一次）："
                                + str(wealth_analysis.validation_error)
                                + "。全部金融数字用给定事实插值；fact_ids必须有效。"
                                "输出不带contract包裹。",
                                conversation_messages=[],
                                principal=execution_principal,
                                agent=AgentDefinition(
                                    agent_id=agent.agent_id,
                                    allowed_capabilities=agent.allowed_capabilities,
                                    instructions=answer_prompt(wealth_analysis, active_skill),
                                    skills=(active_skill,),
                                ),
                                event_sink=event_sink,
                                wealth_context=wealth_context,
                            )
                        )
                        wealth_analysis = apply_answer(
                            wealth_analysis, repaired.answer, active_skill
                        )
                        repaired.state.step_count += result.state.step_count
                        result = repaired
                    except AgentRuntimeError:
                        pass
                await event_sink(
                    "agent_skill.completed"
                    if wealth_analysis.narrative_source == "MODEL_GENERATED"
                    else "agent_skill.failed",
                    active_skill.metadata()
                    | {"generation_source": wealth_analysis.narrative_source},
                )
                result = AgentRunResult(
                    answer="\n\n".join(b.text for b in wealth_analysis.blocks), state=result.state
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
                    statement_evidence=[
                        r
                        for r in result.state.successful_tool_results
                        if r.capability_id == "account.statement"
                    ],
                    account_results=[
                        r.model_dump(mode="json")
                        for r in build_account_results(result.state.successful_tool_results)
                    ]
                    if any(s.skill_id == "banking-assistance" for s in run_agent.skills)
                    else [],
                    steps=result.state.step_count,
                    tool_calls=result.state.tool_call_count,
                )
                return
            if any(
                r.capability_id == "account.statement" for r in result.state.successful_tool_results
            ) and all(
                r.capability_id in {"account.statement", "account.list", "account.get_balance"}
                for r in result.state.successful_tool_results
            ):
                from banking_api.application.account_results import account_query_answer
                from banking_api.application.statement_results import statement_answer
                from banking_api.runtime.base import AgentRunResult

                balances = (
                    account_query_answer(result.state.successful_tool_results)
                    if any(
                        r.capability_id == "account.get_balance"
                        for r in result.state.successful_tool_results
                    )
                    else ""
                )
                result = AgentRunResult(
                    answer="\n\n".join(
                        filter(
                            None, (balances, statement_answer(result.state.successful_tool_results))
                        )
                    ),
                    state=result.state,
                )
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
                        include_account_results=any(
                            s.skill_id == "banking-assistance" for s in run_agent.skills
                        ),
                    )
                    | (
                        {"wealth_analysis": wealth_analysis.model_dump(mode="json")}
                        if wealth_analysis
                        else {}
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
        except SkillSelectionError as exc:
            await self._complete_without_agent(
                claim=claim,
                conversation_id=conversation_id,
                answer=str(exc),
                route=RequestRoute.WEALTH_ANALYSIS,
            )
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

    async def _route(self, current_task: str, wealth_context=None) -> RouteDecision:
        if self.router is None:
            return RouteDecision(
                route=RequestRoute.ACCOUNT_QUERY,
                requested_output=RequestedOutput.ANSWER,
                confidence=1,
            )
        return (
            await self.router.route(current_task, wealth_context=wealth_context)
            if wealth_context
            else await self.router.route(current_task)
        )

    @staticmethod
    def _durable_route(
        *,
        executor_type: ExecutorType | None,
        executor_id: str | None,
        requested_output: RequestedOutput | None,
        personal_banking_route: str | None = None,
    ) -> RouteDecision | None:
        if executor_id is None or requested_output is None:
            return None
        if executor_id in LEGACY_AGENT_ROUTES:
            route = RequestRoute(LEGACY_AGENT_ROUTES[executor_id])
        elif executor_id == PERSONAL_BANKING_AGENT_ID:
            if personal_banking_route not in {
                RequestRoute.ACCOUNT_QUERY,
                RequestRoute.FINANCIAL_ANALYSIS,
                RequestRoute.PERSONAL_BANKING,
            }:
                raise RoutingError("Persisted personal banking skill scope is missing")
            route = RequestRoute(personal_banking_route)
        elif executor_id == "planner:constrained":
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
        if agent_id in LEGACY_AGENT_ROUTES:
            agent_id = PERSONAL_BANKING_AGENT_ID
        if self.agent_registry is None:
            if agent_id == PERSONAL_BANKING_AGENT_ID:
                return PERSONAL_BANKING_AGENT
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
            if executor_id == PERSONAL_BANKING_AGENT_ID:
                task.input_json = {**task.input_json, "personal_banking_route": route.value}
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

    async def _run_wealth(
        self, claim, conversation_id, user_id, request, route, *, body=None, previous=None
    ):
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
            if body:
                draft["product_id"] = body.product_ids[0] if len(body.product_ids) == 1 else None
                draft["account_id"] = body.account_id or (
                    previous.needs.account_id if previous else None
                )
                if direction == "PURCHASE":
                    draft["quantity"] = body.amount or (previous.needs.amount if previous else None)
                    draft["quantity_unit"] = "元" if draft["quantity"] else numeric.unit
            from sqlalchemy import select

            from banking_api.persistence.models import WorkflowModel
            from banking_api.wealth.calculation import WealthError
            from banking_api.wealth.schemas import WealthEditInput

            skill = packaged_catalog().activate("PREPARE_" + direction, request)
            await EventPublisher(session).persist(
                event_type="agent_skill.activated",
                conversation_id=conversation_id,
                task_id=claim.task_id,
                data=skill.metadata(),
            )
            try:
                handler = wealth_workflow(
                    direction, session, self.transfer_workflow_engine.wealth_engine.balances
                )
                linked = previous.answer.workflow_id if previous and previous.answer else None
                linked_model = await session.get(WorkflowModel, linked) if linked else None
                if (
                    linked_model
                    and linked_model.user_id == user_id
                    and linked_model.conversation_id == conversation_id
                    and linked_model.status in {WorkflowStatus.COMMITTING, WorkflowStatus.SUCCEEDED}
                    and not (body and body.intent_frame and body.intent_frame.new_plan)
                ):
                    await session.rollback()
                    await self._complete_without_agent(
                        claim=claim,
                        conversation_id=conversation_id,
                        answer="这笔申请已经提交，不能修改金额或账户。请在理财订单中查看成交和到账进度；如果要另做一笔，请明确开始新的交易。",
                        route=RequestRoute.WEALTH_ANALYSIS,
                        failed_skill=skill,
                        skill_error_code="WORKFLOW_ALREADY_SUBMITTED",
                    )
                    return
                existing = await session.scalar(
                    select(WorkflowModel)
                    .where(
                        WorkflowModel.user_id == user_id,
                        WorkflowModel.conversation_id == conversation_id,
                        WorkflowModel.workflow_type == "WEALTH_" + direction,
                        WorkflowModel.status.in_(
                            [
                                WorkflowStatus.WAITING_FOR_INPUT,
                                WorkflowStatus.READY_FOR_REVIEW,
                                WorkflowStatus.REAUTH_REQUIRED,
                                WorkflowStatus.READY_FOR_COMMIT,
                            ]
                        ),
                    )
                    .order_by(WorkflowModel.created_at.desc())
                    .limit(1)
                )
                if (
                    existing
                    and existing.source_task_id != claim.task_id
                    and not (body and body.intent_frame and body.intent_frame.new_plan)
                ):
                    workflow = await handler.edit(
                        existing.workflow_id,
                        user_id,
                        WealthEditInput(
                            expected_version=existing.version,
                            product_id=draft["product_id"],
                            account_id=draft["account_id"],
                            quantity=draft["quantity"],
                            redeem_all=draft["redeem_all"],
                        ),
                    )
                else:
                    workflow = await handler.create(
                        user_id, conversation_id, claim.task_id, draft, allow_invalid_draft=True
                    )
            except WealthError as exc:
                if direction != "PURCHASE" or exc.code not in {
                    "ASSESSMENT_REQUIRED",
                    "ASSESSMENT_EXPIRED",
                    "SUITABILITY_MISMATCH",
                }:
                    raise
                await session.rollback()
                guidance = {
                    "ASSESSMENT_REQUIRED": "购买理财前，请先完成有效的风险测评。",
                    "ASSESSMENT_EXPIRED": "你的风险测评已失效，购买理财前请重新测评。",
                    "SUITABILITY_MISMATCH": f"当前测评结果不适合购买这些净值型模拟产品。{exc}。",
                }[exc.code]
                await self._complete_without_agent(
                    claim=claim,
                    conversation_id=conversation_id,
                    answer=f"{guidance}\n\n[前往理财中心查看并完成风险测评](/wealth)"
                    "\n\n你仍可先了解产品和风险。完成有效测评后，再按测评结果判断是否适合购买。",
                    route=RequestRoute.WEALTH_ANALYSIS,
                    failed_skill=skill,
                    skill_error_code=exc.code,
                )
                return
            output_analysis = None
            if body:
                from banking_api.wealth.advisory import WealthAdvisoryService
                from banking_api.wealth.answer import apply_answer
                from banking_api.wealth.service import WealthService

                output_analysis = await WealthAdvisoryService(
                    WealthService(
                        session,
                        self.transfer_workflow_engine.wealth_engine.balances,
                        self.wealth_clock,
                    )
                ).analyze(user_id, body, previous)
                output_analysis.source_task_id = claim.task_id
                output_analysis.snapshot_id = claim.task_id
                output_analysis = apply_answer(output_analysis, "", skill)
                output_analysis.answer.workflow_id = workflow.workflow_id
            await EventPublisher(session).persist(
                event_type="agent_skill.completed",
                conversation_id=conversation_id,
                task_id=claim.task_id,
                data=skill.metadata() | {"workflow_id": str(workflow.workflow_id)},
            )
            task_status = (
                TaskStatus.COMPLETED
                if workflow.source_task_id != claim.task_id
                else TaskStatus.WAITING_USER
            )
            await tasks.transition(
                task,
                task_status,
                output={
                    **(
                        {"wealth_analysis": output_analysis.model_dump(mode="json")}
                        if output_analysis
                        else {}
                    ),
                    "route": route.value,
                    "workflow_id": str(workflow.workflow_id),
                    "requested_output": "WORKFLOW",
                },
            )
            await EventPublisher(session).persist(
                event_type="task.completed"
                if task_status == TaskStatus.COMPLETED
                else "task.waiting_user",
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
        failed_skill: ActivatedSkill | None = None,
        skill_error_code: str | None = None,
    ) -> None:
        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            messages = MessageRepository(session)
            publisher = EventPublisher(session)
            task = await self._get_owned(tasks, claim, for_update=True)
            # Trade preparation rolls back its transaction when blocked. Retain the
            # attempted package and outcome in the committed user-facing response.
            if failed_skill is not None:
                for event_type in ("agent_skill.activated", "agent_skill.failed"):
                    await publisher.persist(
                        event_type=event_type,
                        conversation_id=conversation_id,
                        task_id=claim.task_id,
                        data=failed_skill.metadata() | {"error_code": skill_error_code},
                    )
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
        include_account_results: bool = True,
    ) -> dict[str, Any]:
        output: dict[str, Any] = {
            "agent_id": agent_id,
            "assistant_message_id": assistant_message_id,
            "steps": steps,
            "tool_calls": tool_calls,
            "requested_output": requested_output.value,
        }
        if agent_id == PERSONAL_BANKING_AGENT_ID and include_account_results:
            output["account_results"] = [
                result.model_dump(mode="json")
                for result in build_account_results(successful_tool_results)
            ]
            from banking_api.application.statement_results import statement_results

            statements = statement_results(successful_tool_results)
            if statements:
                output["statement_results"] = [page.model_dump(mode="json") for page in statements]
                output["statement_queries"] = [
                    r.arguments
                    for r in successful_tool_results
                    if r.capability_id == "account.statement"
                ]
        if any(r.capability_id.startswith("transaction.") for r in successful_tool_results):
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
        if agent_id == PERSONAL_BANKING_ACCOUNT_AGENT.agent_id:
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
            if output["wealth_results"]:
                output["wealth_final_result_index"] = len(output["wealth_results"]) - 1
        return output

    async def _run_report_pipeline(
        self,
        *,
        claim: TaskExecutionClaim,
        conversation_id: UUID,
        user_id: str,
        agent_id: str,
        snapshot: FinancialAnalysisSnapshot,
        account_results: list[dict[str, Any]] | None = None,
        statement_evidence: list[SuccessfulToolResult] | None = None,
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
            account_results=account_results,
            statement_evidence=statement_evidence,
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
        account_results: list[dict[str, Any]] | None = None,
        statement_evidence: list[SuccessfulToolResult] | None = None,
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
                balances = "\n".join(
                    f"{r['display_name']}当前余额：{r['balance_display']}"
                    for r in account_results or []
                    if r.get("kind") == "ACCOUNT_BALANCE"
                )
                from banking_api.application.statement_results import (
                    statement_answer,
                    statement_results,
                )

                ledger_answer = statement_answer(statement_evidence or [])
                assistant = await messages.create(
                    conversation_id=conversation_id,
                    role=MessageRole.ASSISTANT,
                    content=(balances + "\n\n" if balances else "")
                    + (ledger_answer + "\n\n" if ledger_answer else "")
                    + f"{period_label}消费报告已生成。",
                )
                await tasks.transition(
                    task,
                    TaskStatus.COMPLETED,
                    output={
                        "requested_output": RequestedOutput.MONTHLY_REPORT.value,
                        "agent_id": agent_id,
                        "analysis_snapshot": snapshot.model_dump(mode="json"),
                        "account_results": account_results or [],
                        "statement_results": [
                            p.model_dump(mode="json")
                            for p in statement_results(statement_evidence or [])
                        ],
                        "statement_queries": [r.arguments for r in statement_evidence or []],
                        "skill_id": skill.skill_id,
                        "skill_version": skill.version,
                        "skill_package": packaged_catalog().bind_business_skill(skill).metadata(),
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
                    "skill_package": packaged_catalog()
                    .bind_business_skill(self.skill_registry.get(skill_id))
                    .metadata(),
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
