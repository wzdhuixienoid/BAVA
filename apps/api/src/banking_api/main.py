from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from banking_api import __version__
from banking_api.agents.personal_banking_agent import (
    PERSONAL_BANKING_ACCOUNT_AGENT,
    PERSONAL_BANKING_AGENT,
)
from banking_api.agents.subscription_analysis_agent import SUBSCRIPTION_ANALYSIS_AGENT
from banking_api.api.router import api_router
from banking_api.api.routes.health import router as health_router
from banking_api.application.aa_intent_extractor import AAIntentExtractor
from banking_api.application.operation_recovery_policy import OperationRecoveryPolicy
from banking_api.application.outbox_publication_policy import OutboxPublicationPolicy
from banking_api.application.task_execution_policy import TaskExecutionPolicy
from banking_api.config.demo_time import reference_now
from banking_api.config.settings import get_settings
from banking_api.context.builder import ContextBuilder
from banking_api.domain.enums import RuntimeBackend
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.financial.anomaly_detector import TransactionAnomalyDetector
from banking_api.llm.openai_compatible_provider import OpenAICompatibleProvider
from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.database import session_factory
from banking_api.planning.planner import ConstrainedPlanner
from banking_api.policy.service import PolicyService
from banking_api.registries.agent_registry import AgentRegistry
from banking_api.registries.skill_registry import SkillRegistry
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.routing.request_router import RequestRouter
from banking_api.runtime.event_bus import EventBus
from banking_api.runtime.langgraph.checkpoint import LangGraphCheckpointManager
from banking_api.runtime.langgraph.graph import LangGraphAgentRuntime
from banking_api.runtime.manual_agent_runtime import ManualAgentRuntime
from banking_api.runtime.operation_recovery_worker import OperationRecoveryWorker
from banking_api.runtime.outbox_publisher import OutboxPublisher
from banking_api.runtime.runtime_factory import AgentRuntimeFactory
from banking_api.runtime.schedule_worker import ScheduleWorker
from banking_api.runtime.subscription_notification_worker import SubscriptionNotificationWorker
from banking_api.runtime.task_execution_worker import TaskExecutionWorker
from banking_api.runtime.task_reconciliation import TaskReconciliationService
from banking_api.runtime.task_runner import InProcessTaskRunner
from banking_api.security.authentication import AuthenticationService
from banking_api.skill_runtime.executor import SkillExecutor
from banking_api.skills.monthly_spending_report import MonthlySpendingReportSkill
from banking_api.skills.transaction_anomaly_analysis import TransactionAnomalyAnalysisSkill
from banking_api.skills.wealth_recommendation import WealthRecommendationSkill
from banking_api.subscriptions.provider import MockSubscriptionProvider
from banking_api.tools.banking import (
    build_commit_transfer_tool,
    build_compare_spending_periods_tool,
    build_detect_anomalies_tool,
    build_get_account_statement_tool,
    build_get_balance_tool,
    build_get_category_breakdown_tool,
    build_get_spending_summary_tool,
    build_get_top_transactions_tool,
    build_get_transfer_status_tool,
    build_list_accounts_tool,
    build_search_payees_tool,
)
from banking_api.tools.banking.search_payees import build_list_payees_tool
from banking_api.tools.executor import ToolExecutor
from banking_api.tools.subscriptions import (
    build_subscription_analyze_tool,
    build_subscription_cancel_tool,
    build_subscription_status_tool,
)
from banking_api.transfers.mock_provider import MockTransferProvider
from banking_api.workflows.subscription_cancel.engine import SubscriptionCancellationWorkflow
from banking_api.workflows.subscription_cancel.intent_extractor import (
    SubscriptionCancelIntentExtractor,
)
from banking_api.workflows.transfer.engine import TransferWorkflowEngine
from banking_api.workflows.transfer.intent_extractor import TransferIntentExtractor


def create_app() -> FastAPI:
    settings = get_settings()
    bus = EventBus()
    runtime_factory = AgentRuntimeFactory()
    checkpoint_manager: LangGraphCheckpointManager | None = None
    schedule_worker = None
    subscription_notification_worker = None
    operation_recovery_worker: OperationRecoveryWorker | None = None
    outbox_publisher: OutboxPublisher | None = None
    task_execution_worker: TaskExecutionWorker | None = None

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        nonlocal checkpoint_manager, operation_recovery_worker, outbox_publisher
        nonlocal task_execution_worker, schedule_worker, subscription_notification_worker
        checkpoint_url = settings.langgraph_checkpoint_database_url or settings.database_url
        if checkpoint_url:
            checkpoint_manager = LangGraphCheckpointManager(
                checkpoint_url,
                strict_msgpack=settings.langgraph_strict_msgpack,
            )
            checkpointer = await checkpoint_manager.start()
            runtime_factory.register(
                RuntimeBackend.LANGGRAPH,
                LangGraphAgentRuntime(
                    provider=provider,
                    registry=registry,
                    executor=executor,
                    context_builder=ContextBuilder(),
                    checkpointer=checkpointer,
                    max_steps=settings.agent_max_steps,
                    max_tool_calls=settings.agent_max_tool_calls,
                ),
            )
        if settings.agent_runtime is RuntimeBackend.LANGGRAPH:
            runtime_factory.get(RuntimeBackend.LANGGRAPH)
        if settings.mock_wealth_enabled:
            from banking_api.wealth.catalog import seed_catalog

            async with session_factory() as seed_session:
                await seed_catalog(seed_session)
                await seed_session.commit()
        await TaskReconciliationService(session_factory, bus).reconcile()
        if settings.task_worker_enabled:
            task_execution_worker = TaskExecutionWorker(
                session_factory,
                task_runner,
                policy=TaskExecutionPolicy.from_settings(settings),
                poll_interval_seconds=settings.task_worker_poll_interval_seconds,
                batch_size=settings.task_worker_batch_size,
                max_concurrency=settings.task_worker_max_concurrency,
            )
            task_execution_worker.start()
            application.state.task_execution_worker = task_execution_worker
        if settings.operation_recovery_enabled:
            operation_recovery_worker = OperationRecoveryWorker(
                session_factory,
                bus,
                transfer_engine,
                subscription_engine=subscription_engine,
                policy=OperationRecoveryPolicy.from_settings(settings),
                poll_interval_seconds=settings.operation_recovery_poll_interval_seconds,
                batch_size=settings.operation_recovery_batch_size,
            )
            operation_recovery_worker.start()
            application.state.operation_recovery_worker = operation_recovery_worker
        subscription_notification_worker = SubscriptionNotificationWorker(
            session_factory,
            bank,
            transfer_provider=transfer_provider,
            billing_enabled=settings.mock_subscription_billing_enabled,
        )
        subscription_notification_worker.start()
        application.state.subscription_notification_worker = subscription_notification_worker
        if settings.mock_scheduled_transfers_enabled:
            schedule_worker = ScheduleWorker(session_factory, bus, transfer_engine)
            schedule_worker.start()
            application.state.schedule_worker = schedule_worker
        if settings.outbox_publisher_enabled:
            outbox_publisher = OutboxPublisher(
                session_factory,
                bus,
                policy=OutboxPublicationPolicy.from_settings(settings),
                poll_interval_seconds=settings.outbox_publisher_poll_interval_seconds,
                batch_size=settings.outbox_publisher_batch_size,
            )
            outbox_publisher.start()
            application.state.outbox_publisher = outbox_publisher
        try:
            yield
        finally:
            if subscription_notification_worker is not None:
                await subscription_notification_worker.stop()
            if schedule_worker is not None:
                await schedule_worker.stop()
            if task_execution_worker is not None:
                await task_execution_worker.stop()
            if operation_recovery_worker is not None:
                await operation_recovery_worker.stop()
            if outbox_publisher is not None:
                await outbox_publisher.stop()
            if checkpoint_manager is not None:
                await checkpoint_manager.close()

    application = FastAPI(
        title="AI 银行助理 API",
        version=__version__,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if settings.llm_provider != "openai_compatible":
        raise ValueError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")
    provider = OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    from banking_api.application.aa_service import MOCK_PARTICIPANTS, AAService

    bank = MockBankService(
        fixture_user_ids=frozenset(
            {settings.development_user_id, *MOCK_PARTICIPANTS.values()}
            if settings.mock_participant_login_enabled
            else {settings.development_user_id}
        )
    )
    transfer_provider = MockTransferProvider(session_factory, bank)
    subscription_provider = MockSubscriptionProvider(session_factory, bank)
    analytics = FinancialAnalyticsService(bank)
    anomaly_detector = TransactionAnomalyDetector(bank)
    registry = ToolRegistry()
    registry.register(build_list_accounts_tool(bank))
    registry.register(build_get_account_statement_tool(bank, session_factory))
    registry.register(build_get_balance_tool(bank, transfer_provider.effective_balance))

    async def posted_bank(user_id):
        from banking_api.application.account_statement_service import (
            AccountStatementService,
            PostedAnalysisBank,
        )

        async with session_factory() as session:
            rows = await AccountStatementService(bank, session).posted_transactions(
                user_id=user_id,
                as_of=reference_now(),
            )
        return PostedAnalysisBank(bank, user_id, rows)

    registry.register(build_get_spending_summary_tool(analytics, bank_reader=posted_bank))
    registry.register(build_get_category_breakdown_tool(analytics, bank_reader=posted_bank))
    registry.register(build_compare_spending_periods_tool(analytics, bank_reader=posted_bank))
    registry.register(build_get_top_transactions_tool(analytics, bank_reader=posted_bank))
    registry.register(build_detect_anomalies_tool(anomaly_detector, bank_reader=posted_bank))
    registry.register(build_search_payees_tool(bank, session_factory))
    registry.register(build_list_payees_tool(bank, session_factory))
    registry.register(build_commit_transfer_tool(session_factory, transfer_provider))
    registry.register(build_get_transfer_status_tool(session_factory, transfer_provider))
    registry.register(build_subscription_analyze_tool(session_factory, bank))
    registry.register(build_subscription_cancel_tool(session_factory, subscription_provider))
    registry.register(
        build_subscription_cancel_tool(session_factory, subscription_provider, resume=True)
    )
    registry.register(build_subscription_status_tool(session_factory, subscription_provider))
    from banking_api.wealth.provider import MockWealthProvider
    from banking_api.wealth.tools import WealthExecutionEngine, build_wealth_tools

    wealth_provider = MockWealthProvider(session_factory, transfer_provider.balances)
    if settings.app_environment in {"development", "test"}:
        for spec in build_wealth_tools(
            session_factory, transfer_provider.balances, wealth_provider
        ):
            registry.register(spec)
    executor = ToolExecutor(registry, PolicyService())
    transfer_engine = TransferWorkflowEngine(executor)
    transfer_engine.wealth_engine = WealthExecutionEngine(executor, transfer_provider.balances)
    from banking_api.workflows.transfer.time_intent import ExecutionTimeExtractor

    transfer_engine.time_extractor = ExecutionTimeExtractor(provider)

    async def resolve_aa(**kwargs):
        async with session_factory() as session:
            return await AAService(session, bus, transfer_engine, bank).resolve_payment(**kwargs)

    transfer_engine.aa_resolver = resolve_aa
    subscription_engine = SubscriptionCancellationWorkflow(executor)
    agent_registry = AgentRegistry()
    agent_registry.register(PERSONAL_BANKING_AGENT)
    agent_registry.register(SUBSCRIPTION_ANALYSIS_AGENT)
    from banking_api.agents.wealth_advisor_agent import WEALTH_ADVISOR_AGENT

    if settings.app_environment in {"development", "test"}:
        agent_registry.register(WEALTH_ADVISOR_AGENT)
    skill_registry = SkillRegistry()
    skill_registry.register(MonthlySpendingReportSkill.definition)
    skill_registry.register(WealthRecommendationSkill.definition)
    skill_registry.register(TransactionAnomalyAnalysisSkill.definition)
    router = RequestRouter(provider)
    manual_runtime = ManualAgentRuntime(
        provider=provider,
        registry=registry,
        executor=executor,
        context_builder=ContextBuilder(),
        agent=PERSONAL_BANKING_ACCOUNT_AGENT,
        max_steps=settings.agent_max_steps,
        max_tool_calls=settings.agent_max_tool_calls,
    )
    runtime_factory.register(RuntimeBackend.MANUAL, manual_runtime)
    application.state.event_bus = bus
    application.state.authentication_service = AuthenticationService(settings)
    application.state.tool_registry = registry
    application.state.agent_registry = agent_registry
    application.state.skill_registry = skill_registry
    application.state.request_router = router
    application.state.runtime_factory = runtime_factory
    application.state.llm_provider = provider
    application.state.transfer_workflow_engine = transfer_engine
    application.state.subscription_workflow_engine = subscription_engine
    transfer_engine.mock_scheduling_supported = isinstance(transfer_provider, MockTransferProvider)
    application.state.transfer_provider = transfer_provider
    application.state.wealth_provider = wealth_provider
    application.state.subscription_provider = subscription_provider
    application.state.mock_bank = bank
    task_runner = InProcessTaskRunner(
        session_factory,
        bus,
        runtime_factory,
        wealth_clock=lambda: wealth_provider.clock() if wealth_provider else reference_now(),
        default_backend=settings.agent_runtime,
        router=router,
        agent_registry=agent_registry,
        skill_registry=skill_registry,
        skill_executor=SkillExecutor(provider),
        aa_intent_extractor=AAIntentExtractor(provider),
        aa_bank=bank,
        transfer_intent_extractor=TransferIntentExtractor(
            provider, time_extractor=transfer_engine.time_extractor
        ),
        transfer_workflow_engine=transfer_engine,
        subscription_intent_extractor=SubscriptionCancelIntentExtractor(provider),
        subscription_workflow_engine=subscription_engine,
        planner=ConstrainedPlanner(provider),
    )
    application.state.task_runner = task_runner
    from fastapi import Request
    from fastapi.responses import JSONResponse

    from banking_api.wealth.calculation import WealthError

    @application.exception_handler(WealthError)
    async def wealth_error_handler(request: Request, exc: WealthError):
        return JSONResponse(
            status_code=404 if exc.code == "NOT_FOUND" else 422,
            content={"detail": {"code": exc.code, "message": str(exc)}},
        )

    from banking_api.security.guard import SecurityWriteLockedError

    @application.exception_handler(SecurityWriteLockedError)
    async def wealth_locked_handler(request: Request, exc: SecurityWriteLockedError):
        return JSONResponse(
            status_code=423,
            content={
                "detail": {
                    "code": "SECURITY_WRITE_LOCKED",
                    "message": "安全保护已启动，新的业务写操作已暂停",
                }
            },
        )

    application.include_router(health_router)
    application.include_router(api_router)
    return application


app = create_app()
