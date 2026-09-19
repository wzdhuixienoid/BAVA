from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from banking_api.api.router import api_router
from banking_api.api.routes.health import router as health_router
from banking_api.application.bootstrap_runtime import BootstrapRuntime
from banking_api.config.settings import get_settings
from banking_api.persistence.database import session_factory
from banking_api.runtime.event_bus import EventBus


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title="AI Banking Agent API", version="0.1.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    bus = EventBus()
    application.state.event_bus = bus
    application.state.bootstrap_runtime = BootstrapRuntime(
        session_factory, bus, delay_seconds=settings.bootstrap_delay_seconds
    )
    application.include_router(health_router)
    application.include_router(api_router)
    return application


app = create_app()

