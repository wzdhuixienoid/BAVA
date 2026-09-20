from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from banking_api.agents.minimal_banking_agent import MINIMAL_BANKING_AGENT
from banking_api.api.router import api_router
from banking_api.api.routes.health import router as health_router
from banking_api.config.settings import get_settings
from banking_api.context.builder import ContextBuilder
from banking_api.llm.openai_compatible_provider import OpenAICompatibleProvider
from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.database import session_factory
from banking_api.policy.service import PolicyService
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.runtime.agent_runtime import AgentRuntime
from banking_api.runtime.event_bus import EventBus
from banking_api.runtime.task_runner import InProcessTaskRunner
from banking_api.tools.banking import build_get_balance_tool, build_list_accounts_tool
from banking_api.tools.executor import ToolExecutor


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title="AI 银行助理 API", version="0.2.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    bus = EventBus()
    if settings.llm_provider != "openai_compatible":
        raise ValueError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")
    provider = OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    bank = MockBankService()
    registry = ToolRegistry()
    registry.register(build_list_accounts_tool(bank))
    registry.register(build_get_balance_tool(bank))
    executor = ToolExecutor(registry, PolicyService())
    runtime = AgentRuntime(
        provider=provider,
        registry=registry,
        executor=executor,
        context_builder=ContextBuilder(),
        agent=MINIMAL_BANKING_AGENT,
        max_steps=settings.agent_max_steps,
        max_tool_calls=settings.agent_max_tool_calls,
    )
    application.state.event_bus = bus
    application.state.tool_registry = registry
    application.state.task_runner = InProcessTaskRunner(session_factory, bus, runtime)
    application.include_router(health_router)
    application.include_router(api_router)
    return application


app = create_app()
