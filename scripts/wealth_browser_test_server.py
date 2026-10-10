"""Isolated browser acceptance harness. Private clock control is a local test file, never HTTP."""

import argparse
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

import uvicorn
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def run(database: Path, control: Path, port: int):
    if "test" not in database.name.lower() or "test" not in control.name.lower():
        raise ValueError(
            "Browser acceptance requires explicitly named test database/control files"
        )
    os.environ.update(
        APP_ENVIRONMENT="test",
        AUTH_MODE="development",
        MOCK_WEALTH_ENABLED="true",
        DEVELOPMENT_USER_ID="dev-user-001",
        MOCK_REAUTH_CODE="246810",
        CORS_ORIGINS='["http://localhost:3011"]',
    )
    from banking_api.config.settings import get_settings

    get_settings.cache_clear()
    from banking_api import main
    from banking_api.application.operation_recovery_policy import (
        OperationRecoveryPolicy,
    )
    from banking_api.persistence.database import Base, get_session
    from banking_api.runtime.operation_recovery_worker import OperationRecoveryWorker
    from banking_api.wealth.catalog import seed_catalog
    from banking_api.wealth.workflow import WealthWorkflow

    engine = create_async_engine(f"sqlite+aiosqlite:///{database.resolve()}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        await seed_catalog(session)
        await session.commit()

    def state():
        return json.loads(control.read_text())

    def clock():
        value = datetime.fromisoformat(state()["now"])
        if value.tzinfo is None:
            raise ValueError("Test clock requires explicit timezone")
        return value

    # Only Wealth authority uses this clock; Guard and other business clocks remain unchanged.
    original_init = WealthWorkflow.__init__

    def init(self, session, balances, *args, **kwargs):
        original_init(self, session, balances, clock, kwargs.get("reauth_provider"))

    WealthWorkflow.__init__ = init
    main.session_factory = factory
    current = [None]
    worker = [None]
    mode = [None]

    async def sessions():
        async with factory() as session:
            yield session

    def assemble():
        enabled = bool(state()["enabled"])
        os.environ["MOCK_WEALTH_ENABLED"] = str(enabled).lower()
        get_settings.cache_clear()
        app = main.create_app()
        app.dependency_overrides[get_session] = sessions
        app.state.wealth_provider.clock = clock
        app.state.wealth_provider.fault_mode = state().get("fault_mode", "SUCCESS")
        current[0] = app
        worker[0] = OperationRecoveryWorker(
            factory,
            app.state.event_bus,
            app.state.transfer_workflow_engine,
            clock=clock,
            policy=OperationRecoveryPolicy.from_settings(),
            poll_interval_seconds=1,
            batch_size=10,
        )
        mode[0] = enabled

    assemble()

    async def dispatch(scope, receive, send):
        await current[0](scope, receive, send)

    async def recovery():
        while True:
            if bool(state()["enabled"]) != mode[0]:
                assemble()  # Recreates all tools/provider wiring with the new feature flag.
            await worker[0].run_once()
            await asyncio.sleep(0.5)

    recover_task = asyncio.create_task(recovery())
    server = uvicorn.Server(
        uvicorn.Config(dispatch, host="127.0.0.1", port=port, lifespan="off")
    )
    try:
        await server.serve()
    finally:
        recover_task.cancel()
        await asyncio.gather(recover_task, return_exceptions=True)
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8011)
    args = parser.parse_args()
    asyncio.run(run(args.database, args.control, args.port))
