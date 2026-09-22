from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from banking_api.agents.financial_analysis_agent import FINANCIAL_ANALYSIS_AGENT_ID
from banking_api.agents.minimal_banking_agent import MINIMAL_BANKING_AGENT
from banking_api.agents.models import AgentDefinition
from banking_api.application.conversation_service import to_message
from banking_api.domain.enums import ExecutorType, MessageRole, RuntimeBackend, TaskStatus
from banking_api.financial.analysis_snapshot import build_financial_analysis_snapshot
from banking_api.persistence.repositories.messages import MessageRepository
from banking_api.persistence.repositories.tasks import TaskRepository
from banking_api.registries.agent_registry import AgentRegistry
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

UNSUPPORTED_MESSAGE = (
    "当前只支持账户列表、余额查询，以及消费汇总、分类、环比和主要交易分析。"
    "暂不支持转账、投资理财、卡片或其他账户写操作。"
)

ROUTE_AGENT_IDS = {
    RequestRoute.MINIMAL_BANKING: MINIMAL_BANKING_AGENT.agent_id,
    RequestRoute.FINANCIAL_ANALYSIS: FINANCIAL_ANALYSIS_AGENT_ID,
}


class InProcessTaskRunner:
    """Runs one agent task outside the request's database session."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bus: EventBus,
        runtime_factory: AgentRuntimeFactory,
        default_backend: RuntimeBackend = RuntimeBackend.MANUAL,
        router: RequestRouter | None = None,
        agent_registry: AgentRegistry | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.bus = bus
        self.runtime_factory = runtime_factory
        self.default_backend = default_backend
        self.router = router
        self.agent_registry = agent_registry

    async def run(self, task_id: UUID) -> None:
        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            messages = MessageRepository(session)
            publisher = EventPublisher(session, self.bus)
            task = await tasks.get(task_id)
            if task is None or task.status is not TaskStatus.PENDING:
                return
            message_id = UUID(str(task.input_json["message_id"]))
            current_message = await messages.get(message_id)
            if current_message is None:
                return
            conversation_messages = [
                to_message(message)
                for message in await messages.list_for_conversation(task.conversation_id)
            ]
            current_task = current_message.content
            conversation_id = task.conversation_id
            runtime_backend = task.runtime_backend
            await tasks.transition(
                task,
                TaskStatus.RUNNING,
                progress_message="正在理解请求",
            )
            started = await publisher.persist(
                event_type="task.started",
                conversation_id=conversation_id,
                task_id=task_id,
                data={
                    "status": task.status.value,
                    "version": task.version,
                    "runtime_backend": runtime_backend.value,
                    "checkpoint_enabled": runtime_backend is RuntimeBackend.LANGGRAPH,
                },
            )
            progress = await publisher.persist(
                event_type="task.progress",
                conversation_id=conversation_id,
                task_id=task_id,
                data={"message": "正在理解请求", "version": task.version},
            )
            await session.commit()
            await publisher.publish_persisted(started, progress)

        async def event_sink(event_type: str, data: dict[str, Any]) -> None:
            await self._persist_runtime_event(
                task_id=task_id,
                conversation_id=conversation_id,
                event_type=event_type,
                data=data,
            )

        try:
            decision = await self._route(current_task)
            executor_id = ROUTE_AGENT_IDS.get(decision.route)
            await self._persist_route(
                task_id=task_id,
                conversation_id=conversation_id,
                route=decision.route,
                executor_id=executor_id,
            )
            if decision.route is RequestRoute.UNSUPPORTED:
                await self._complete_without_agent(
                    task_id=task_id,
                    conversation_id=conversation_id,
                    answer=UNSUPPORTED_MESSAGE,
                    route=decision.route,
                )
                return
            if executor_id is None:
                raise RoutingError("Route does not map to an executor")
            agent = self._get_agent(executor_id)
            if (
                agent.agent_id == FINANCIAL_ANALYSIS_AGENT_ID
                and runtime_backend is not RuntimeBackend.LANGGRAPH
            ):
                raise AgentRuntimeError(
                    "FINANCIAL_AGENT_REQUIRES_LANGGRAPH",
                    "FinancialAnalysisAgent requires LangGraph runtime",
                )
            runtime = self.runtime_factory.get(runtime_backend)
            result = await runtime.run(
                AgentRunRequest(
                    task_id=task_id,
                    conversation_id=conversation_id,
                    current_task=current_task,
                    conversation_messages=conversation_messages,
                    authenticated=True,
                    agent=agent,
                    event_sink=event_sink,
                )
            )
            async with self.session_factory() as session:
                tasks = TaskRepository(session)
                messages = MessageRepository(session)
                publisher = EventPublisher(session, self.bus)
                task = await tasks.get(task_id)
                if task is None:
                    return
                assistant = await messages.create(
                    conversation_id=conversation_id,
                    role=MessageRole.ASSISTANT,
                    content=result.answer,
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
                    ),
                )
                completed = await publisher.persist(
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
                message_completed = await publisher.persist(
                    event_type="conversation.message.completed",
                    conversation_id=conversation_id,
                    task_id=task_id,
                    data={"message_id": str(assistant.message_id), "role": assistant.role.value},
                )
                await session.commit()
                await publisher.publish_persisted(completed, message_completed)
        except RoutingError:
            await self._fail(
                task_id,
                conversation_id,
                {
                    "category": "INTERNAL",
                    "code": "ROUTING_FAILED",
                    "message": "Request routing failed",
                    "retryable": False,
                },
            )
        except AgentRuntimeError as exc:
            await self._fail(task_id, conversation_id, exc.as_dict())
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
            await self._fail(task_id, conversation_id, error)

    async def _route(self, current_task: str) -> RouteDecision:
        if self.router is None:
            return RouteDecision(route=RequestRoute.MINIMAL_BANKING, confidence=1)
        return await self.router.route(current_task)

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
        task_id: UUID,
        conversation_id: UUID,
        route: RequestRoute,
        executor_id: str | None,
    ) -> None:
        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            publisher = EventPublisher(session, self.bus)
            task = await tasks.get(task_id)
            if task is None:
                return
            if executor_id is not None:
                await tasks.assign_executor(
                    task,
                    executor_type=ExecutorType.AGENT,
                    executor_id=executor_id,
                )
            routed = await publisher.persist(
                event_type="request.routed",
                conversation_id=conversation_id,
                task_id=task_id,
                data={"route": route.value, "executor_id": executor_id},
            )
            await session.commit()
            await publisher.publish_persisted(routed)

    async def _complete_without_agent(
        self,
        *,
        task_id: UUID,
        conversation_id: UUID,
        answer: str,
        route: RequestRoute,
    ) -> None:
        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            messages = MessageRepository(session)
            publisher = EventPublisher(session, self.bus)
            task = await tasks.get(task_id)
            if task is None:
                return
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
                    "assistant_message_id": str(assistant.message_id),
                },
            )
            completed = await publisher.persist(
                event_type="task.completed",
                conversation_id=conversation_id,
                task_id=task_id,
                data={
                    "status": task.status.value,
                    "version": task.version,
                    "runtime_backend": task.runtime_backend.value,
                    "checkpoint_enabled": False,
                },
            )
            message_completed = await publisher.persist(
                event_type="conversation.message.completed",
                conversation_id=conversation_id,
                task_id=task_id,
                data={"message_id": str(assistant.message_id), "role": assistant.role.value},
            )
            await session.commit()
            await publisher.publish_persisted(completed, message_completed)

    @staticmethod
    def _build_task_output(
        *,
        agent_id: str,
        assistant_message_id: str,
        steps: int,
        tool_calls: int,
        successful_tool_results: list[SuccessfulToolResult],
    ) -> dict[str, Any]:
        output: dict[str, Any] = {
            "agent_id": agent_id,
            "assistant_message_id": assistant_message_id,
            "steps": steps,
            "tool_calls": tool_calls,
        }
        if agent_id == FINANCIAL_ANALYSIS_AGENT_ID:
            output["analysis_snapshot"] = build_financial_analysis_snapshot(
                successful_tool_results
            ).model_dump(mode="json")
        return output

    async def _persist_runtime_event(
        self,
        *,
        task_id: UUID,
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
            publisher = EventPublisher(session, self.bus)
            persisted = []
            task = await tasks.get(task_id)
            if task is None:
                return
            if progress_message is not None and task.progress_message != progress_message:
                await tasks.update_progress(task, progress_message)
                persisted.append(
                    await publisher.persist(
                        event_type="task.progress",
                        conversation_id=conversation_id,
                        task_id=task_id,
                        data={"message": progress_message, "version": task.version},
                    )
                )
            persisted.append(
                await publisher.persist(
                    event_type=event_type,
                    conversation_id=conversation_id,
                    task_id=task_id,
                    data=data,
                )
            )
            await session.commit()
            await publisher.publish_persisted(*persisted)

    async def _fail(
        self, task_id: UUID, conversation_id: UUID, error: dict[str, Any]
    ) -> None:
        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            publisher = EventPublisher(session, self.bus)
            task = await tasks.get(task_id)
            if task is None:
                return
            await tasks.transition(task, TaskStatus.FAILED, error=error)
            failed = await publisher.persist(
                event_type="task.failed",
                conversation_id=conversation_id,
                task_id=task_id,
                data={
                    "status": task.status.value,
                    "version": task.version,
                    "code": error["code"],
                    "runtime_backend": task.runtime_backend.value,
                    "checkpoint_enabled": task.runtime_backend is RuntimeBackend.LANGGRAPH,
                },
            )
            await session.commit()
            await publisher.publish_persisted(failed)
