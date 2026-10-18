"""Isolated browser acceptance harness. Private clock control is a local test file, never HTTP."""

import argparse
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

import uvicorn
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def run(
    database: Path, control: Path, port: int, advisor_history=False, real_model=False
):
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
        REAUTH_PROVIDER="mock",
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

    if advisor_history:
        from banking_api.domain.enums import ExecutorType, MessageRole, TaskStatus
        from banking_api.persistence.repositories.conversations import (
            ConversationRepository,
        )
        from banking_api.persistence.repositories.messages import MessageRepository
        from banking_api.persistence.repositories.tasks import TaskRepository
        from banking_api.wealth.schemas import WealthReadResult
        from banking_api.wealth.service import WealthService

        async with factory() as session:
            conversation = await ConversationRepository(session).create(
                user_id="dev-user-001", title="历史推荐（隔离测试）"
            )
            message = await MessageRepository(session).create(
                conversation_id=conversation.conversation_id,
                role=MessageRole.USER,
                content="推荐稳健理财",
            )
            task = await TaskRepository(session).create(
                conversation_id=conversation.conversation_id,
                user_id="dev-user-001",
                task_type="USER_REQUEST",
                input_data={"message_id": str(message.message_id)},
            )
            task.executor_type, task.executor_id = (
                ExecutorType.AGENT,
                "agent:wealth-advisor",
            )
            product = await WealthService(session).product(
                "mock-wealth-01", "dev-user-001"
            )
            await TaskRepository(session).transition(
                task,
                TaskStatus.COMPLETED,
                output={
                    "wealth_results": [
                        WealthReadResult(products=[product]).model_dump(mode="json")
                    ]
                },
            )
            await MessageRepository(session).create(
                conversation_id=conversation.conversation_id,
                role=MessageRole.ASSISTANT,
                content="历史工具原文 mock-wealth-01 /api/v1/wealth/documents/old",
            )
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
    task_worker = [None]
    publisher = [None]

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
        from banking_api.application.outbox_publication_policy import (
            OutboxPublicationPolicy,
        )
        from banking_api.application.task_execution_policy import TaskExecutionPolicy
        from banking_api.context.builder import ContextBuilder
        from banking_api.domain.enums import RuntimeBackend
        from banking_api.llm.models import LLMResponse
        from banking_api.runtime.langgraph.graph import LangGraphAgentRuntime
        from banking_api.runtime.outbox_publisher import OutboxPublisher
        from banking_api.runtime.task_execution_worker import TaskExecutionWorker
        from langgraph.checkpoint.memory import InMemorySaver

        class TestAdvisor:
            async def generate(self, request):
                instruction = request.messages[0].content
                if "语义提取器" in instruction:
                    from banking_api.wealth.semantic import fallback_frame

                    data = json.loads(request.messages[1].content)
                    return LLMResponse(
                        content=fallback_frame(data["message"]).model_dump_json()
                    )
                data = json.loads(instruction.rsplit("\n\n", 1)[-1])
                paragraph = []
                if data["candidates"]:
                    candidate = data["candidates"][0]
                    paragraph = [
                        {
                            "block_id": "fresh-prose",
                            "title": "产品取舍",
                            "text": "{{"
                            + candidate["fact_id"]
                            + ".name}}提供净值投资的选择，但现金不能随申请立即到账。",
                            "fact_ids": [candidate["fact_id"]],
                            "evidence_ids": [],
                        }
                    ]
                return LLMResponse(
                    content=json.dumps(
                        {
                            "headline": data["hard_result"]
                            or "你希望这笔钱获得收益，我们可以一起看清费用与用款安排的取舍。",
                            "paragraphs": paragraph,
                            "questions": []
                            if data["action"].startswith("PREPARE_")
                            else data["needs"]["clarification_questions"][:2],
                            "relations": [],
                        },
                        ensure_ascii=False,
                    )
                )

        selected_provider = app.state.llm_provider if real_model else TestAdvisor()
        app.state.llm_provider = selected_provider
        app.state.task_runner.router._provider = selected_provider
        app.state.runtime_factory.register(
            RuntimeBackend.LANGGRAPH,
            LangGraphAgentRuntime(
                provider=selected_provider,
                registry=app.state.tool_registry,
                executor=app.state.transfer_workflow_engine._executor,
                context_builder=ContextBuilder(),
                checkpointer=InMemorySaver(),
            ),
        )
        task_worker[0] = TaskExecutionWorker(
            factory,
            app.state.task_runner,
            policy=TaskExecutionPolicy.from_settings(),
            poll_interval_seconds=0.5,
            batch_size=4,
            max_concurrency=4,
        )
        publisher[0] = OutboxPublisher(
            factory,
            app.state.event_bus,
            policy=OutboxPublicationPolicy.from_settings(),
            poll_interval_seconds=0.5,
            batch_size=50,
        )
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
            await task_worker[0].run_once()
            await publisher[0].run_once()
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
    parser.add_argument("--advisor-history", action="store_true")
    parser.add_argument("--real-model", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        run(
            args.database,
            args.control,
            args.port,
            args.advisor_history,
            args.real_model,
        )
    )
