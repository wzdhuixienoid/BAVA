from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from banking_api.agents.financial_analysis_agent import FINANCIAL_ANALYSIS_AGENT
from banking_api.agents.minimal_banking_agent import MINIMAL_BANKING_AGENT
from banking_api.api.router import api_router
from banking_api.api.routes.health import router as health_router
from banking_api.application.operation_recovery_policy import OperationRecoveryPolicy
from banking_api.application.outbox_publication_policy import OutboxPublicationPolicy
from banking_api.config.settings import get_settings
from banking_api.context.builder import ContextBuilder
from banking_api.domain.enums import RuntimeBackend
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.llm.openai_compatible_provider import OpenAICompatibleProvider
from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.database import session_factory
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
from banking_api.runtime.task_reconciliation import TaskReconciliationService
from banking_api.runtime.task_runner import InProcessTaskRunner
from banking_api.skill_runtime.executor import SkillExecutor
from banking_api.skills.monthly_spending_report import MonthlySpendingReportSkill
from banking_api.tools.banking import (
    build_commit_transfer_tool,
    build_compare_spending_periods_tool,
    build_get_balance_tool,
    build_get_category_breakdown_tool,
    build_get_spending_summary_tool,
    build_get_top_transactions_tool,
    build_get_transfer_status_tool,
    build_list_accounts_tool,
    build_search_payees_tool,
)
from banking_api.tools.executor import ToolExecutor
from banking_api.transfers.mock_provider import MockTransferProvider
from banking_api.workflows.transfer.engine import TransferWorkflowEngine
from banking_api.workflows.transfer.intent_extractor import TransferIntentExtractor


def create_app() -> FastAPI:
    settings = get_settings()
    bus = EventBus()
    runtime_factory = AgentRuntimeFactory()
    checkpoint_manager: LangGraphCheckpointManager | None = None
    operation_recovery_worker: OperationRecoveryWorker | None = None
    outbox_publisher: OutboxPublisher | None = None

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        nonlocal checkpoint_manager, operation_recovery_worker, outbox_publisher
        checkpoint_url = (
            settings.langgraph_checkpoint_database_url or settings.database_url
        )
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
        await TaskReconciliationService(session_factory, bus).reconcile()
        if settings.operation_recovery_enabled:
            operation_recovery_worker = OperationRecoveryWorker(
                session_factory,
                bus,
                transfer_engine,
                policy=OperationRecoveryPolicy.from_settings(settings),
                poll_interval_seconds=settings.operation_recovery_poll_interval_seconds,
                batch_size=settings.operation_recovery_batch_size,
            )
            operation_recovery_worker.start()
            application.state.operation_recovery_worker = operation_recovery_worker
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
            if outbox_publisher is not None:
                await outbox_publisher.stop()
            if operation_recovery_worker is not None:
                await operation_recovery_worker.stop()
            if checkpoint_manager is not None:
                await checkpoint_manager.close()

    application = FastAPI(
        title="AI 银行助理 API",
        version="0.5.3",
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
    bank = MockBankService()
    transfer_provider = MockTransferProvider(session_factory, bank)
    analytics = FinancialAnalyticsService(bank)
    registry = ToolRegistry()
    registry.register(build_list_accounts_tool(bank))
    registry.register(build_get_balance_tool(bank, transfer_provider.effective_balance))
    registry.register(build_get_spending_summary_tool(analytics))
    registry.register(build_get_category_breakdown_tool(analytics))
    registry.register(build_compare_spending_periods_tool(analytics))
    registry.register(build_get_top_transactions_tool(analytics))
    registry.register(build_search_payees_tool(bank))
    registry.register(build_commit_transfer_tool(session_factory, transfer_provider))
    registry.register(build_get_transfer_status_tool(session_factory, transfer_provider))
    executor = ToolExecutor(registry, PolicyService())
    transfer_engine = TransferWorkflowEngine(executor)
    agent_registry = AgentRegistry()
    agent_registry.register(MINIMAL_BANKING_AGENT)
    agent_registry.register(FINANCIAL_ANALYSIS_AGENT)
    skill_registry = SkillRegistry()
    skill_registry.register(MonthlySpendingReportSkill.definition)
    router = RequestRouter(provider)
    manual_runtime = ManualAgentRuntime(
        provider=provider,
        registry=registry,
        executor=executor,
        context_builder=ContextBuilder(),
        agent=MINIMAL_BANKING_AGENT,
        max_steps=settings.agent_max_steps,
        max_tool_calls=settings.agent_max_tool_calls,
    )
    runtime_factory.register(RuntimeBackend.MANUAL, manual_runtime)
    application.state.event_bus = bus
    application.state.tool_registry = registry
    application.state.agent_registry = agent_registry
    application.state.skill_registry = skill_registry
    application.state.request_router = router
    application.state.runtime_factory = runtime_factory
    application.state.transfer_workflow_engine = transfer_engine
    application.state.transfer_provider = transfer_provider
    application.state.task_runner = InProcessTaskRunner(
        session_factory,
        bus,
        runtime_factory,
        default_backend=settings.agent_runtime,
        router=router,
        agent_registry=agent_registry,
        skill_registry=skill_registry,
        skill_executor=SkillExecutor(provider),
        transfer_intent_extractor=TransferIntentExtractor(provider),
        transfer_workflow_engine=transfer_engine,
    )
    application.include_router(health_router)
    application.include_router(api_router)
    return application


app = create_app()
