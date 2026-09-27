import asyncio
import logging
import os
import socket
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from banking_api.application.task_execution_policy import TaskExecutionPolicy
from banking_api.domain.enums import TaskStatus
from banking_api.persistence.repositories.tasks import (
    TaskExecutionClaim,
    TaskRepository,
)
from banking_api.runtime.event_publisher import EventPublisher

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


class TaskLeaseLostError(Exception):
    """Raised when an execution attempt no longer owns its durable Task lease."""


class TaskExecutionWorker:
    """Claims durable Tasks and delegates their execution to the existing executor."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        executor,  # type: ignore[no-untyped-def]
        *,
        policy: TaskExecutionPolicy,
        poll_interval_seconds: float,
        batch_size: int,
        max_concurrency: int,
        worker_id: str | None = None,
        clock=_now,  # type: ignore[no-untyped-def]
    ) -> None:
        self._session_factory = session_factory
        self._executor = executor
        self._policy = policy
        self._poll_interval_seconds = poll_interval_seconds
        self._batch_size = min(batch_size, max_concurrency)
        self._max_concurrency = max_concurrency
        self._clock = clock
        self.worker_id = worker_id or (
            f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex}"
        )
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self.run(), name=f"task-execution:{self.worker_id}"
        )
        logger.info("task worker started worker=%s", self.worker_id)

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await self._task
            self._task = None
        logger.info("task worker stopped worker=%s", self.worker_id)

    async def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("task worker scan failed worker=%s", self.worker_id)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._poll_interval_seconds
                )
            except TimeoutError:
                pass

    async def run_once(self) -> int:
        claims = await self._claim_due(limit=self._batch_size)
        if claims:
            await asyncio.gather(*(self._execute_claim(claim) for claim in claims))
        return len(claims)

    async def run_task_once(self, task_id: UUID) -> bool:
        """Execute one exact Task through the same durable claim path."""
        claims = await self._claim_due(limit=1, task_id=task_id)
        if not claims:
            return False
        await self._execute_claim(claims[0])
        return True

    async def _claim_due(
        self, *, limit: int, task_id: UUID | None = None
    ) -> list[TaskExecutionClaim]:
        now = self._clock()
        async with self._session_factory() as session:
            claims = await TaskRepository(session).claim_due(
                lease_owner=self.worker_id,
                now=now,
                lease_expires_at=now + self._policy.lease_duration,
                limit=limit,
                task_id=task_id,
            )
            publisher = EventPublisher(session)
            for claim in claims:
                await publisher.persist(
                    event_type="task.started",
                    conversation_id=claim.conversation_id,
                    task_id=claim.task_id,
                    data={
                        "status": "RUNNING",
                        "version": claim.version,
                        "runtime_backend": claim.runtime_backend.value,
                        "checkpoint_enabled": (
                            claim.runtime_backend.value == "langgraph"
                        ),
                        "attempt": claim.attempt,
                        "reclaimed": claim.reclaimed,
                    },
                )
                await publisher.persist(
                    event_type="task.progress",
                    conversation_id=claim.conversation_id,
                    task_id=claim.task_id,
                    data={"message": "正在理解请求", "version": claim.version},
                )
            await session.commit()
        for claim in claims:
            logger.info(
                "task claimed task_id=%s worker=%s attempt=%s reclaimed=%s",
                claim.task_id,
                self.worker_id,
                claim.attempt,
                claim.reclaimed,
            )
        return claims

    async def _execute_claim(self, claim: TaskExecutionClaim) -> None:
        execution = asyncio.create_task(
            self._executor.execute_claimed(claim, policy=self._policy),
            name=f"task-attempt:{claim.task_id}:{claim.attempt}",
        )
        heartbeat = asyncio.create_task(
            self._heartbeat(claim, execution),
            name=f"task-heartbeat:{claim.task_id}:{claim.attempt}",
        )
        logger.info(
            "task execution attempt started task_id=%s worker=%s attempt=%s",
            claim.task_id,
            self.worker_id,
            claim.attempt,
        )
        try:
            await execution
            async with self._session_factory() as session:
                task = await TaskRepository(session).get(claim.task_id)
            if task is not None and task.status is TaskStatus.COMPLETED:
                logger.info(
                    "task execution attempt succeeded task_id=%s worker=%s attempt=%s",
                    claim.task_id,
                    self.worker_id,
                    claim.attempt,
                )
            else:
                logger.info(
                    "task execution attempt finished task_id=%s worker=%s attempt=%s "
                    "result=%s",
                    claim.task_id,
                    self.worker_id,
                    claim.attempt,
                    task.status.value if task is not None else "MISSING",
                )
        except TaskLeaseLostError:
            logger.warning(
                "stale task worker fenced task_id=%s worker=%s attempt=%s",
                claim.task_id,
                self.worker_id,
                claim.attempt,
            )
        except asyncio.CancelledError:
            if self._stop_event.is_set():
                raise
            logger.warning(
                "task execution cancelled after lease loss task_id=%s worker=%s attempt=%s",
                claim.task_id,
                self.worker_id,
                claim.attempt,
            )
        except Exception:
            # Persistence/DB failure deliberately leaves the lease to expire. The
            # next owner reloads authoritative Task/domain state before retrying.
            logger.exception(
                "task execution attempt failed task_id=%s worker=%s attempt=%s",
                claim.task_id,
                self.worker_id,
                claim.attempt,
            )
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    async def _heartbeat(
        self, claim: TaskExecutionClaim, execution: asyncio.Task[None]
    ) -> None:
        interval = self._policy.heartbeat_interval.total_seconds()
        while not execution.done():
            await asyncio.sleep(interval)
            if execution.done():
                return
            now = self._clock()
            async with self._session_factory() as session:
                renewed = await TaskRepository(session).renew_lease(
                    task_id=claim.task_id,
                    lease_owner=claim.lease_owner,
                    attempt=claim.attempt,
                    now=now,
                    lease_expires_at=now + self._policy.lease_duration,
                )
                if renewed:
                    await session.commit()
                else:
                    await session.rollback()
            if not renewed:
                logger.warning(
                    "task lease lost task_id=%s worker=%s attempt=%s",
                    claim.task_id,
                    self.worker_id,
                    claim.attempt,
                )
                execution.cancel()
                return
            logger.info(
                "task lease renewed task_id=%s worker=%s attempt=%s",
                claim.task_id,
                self.worker_id,
                claim.attempt,
            )
