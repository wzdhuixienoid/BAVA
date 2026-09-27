import asyncio
import logging
import os
import socket
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from banking_api.application.operation_recovery_policy import OperationRecoveryPolicy
from banking_api.application.operation_service import (
    OperationLeaseLostError,
    OperationService,
)
from banking_api.persistence.repositories.operations import (
    OperationClaim,
    OperationRepository,
)
from banking_api.runtime.event_bus import EventBus
from banking_api.workflows.transfer.engine import TransferWorkflowEngine

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


class OperationRecoveryWorker:
    """Polls PostgreSQL for due transfer Operations and reconciles claimed rows."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bus: EventBus,
        engine: TransferWorkflowEngine,
        *,
        policy: OperationRecoveryPolicy,
        poll_interval_seconds: float,
        batch_size: int,
        worker_id: str | None = None,
        clock=_now,  # type: ignore[no-untyped-def]
    ) -> None:
        self._session_factory = session_factory
        self._bus = bus
        self._engine = engine
        self._policy = policy
        self._poll_interval_seconds = poll_interval_seconds
        self._batch_size = batch_size
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
            self.run(), name=f"operation-recovery:{self.worker_id}"
        )
        logger.info("operation recovery worker started worker=%s", self.worker_id)

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await self._task
            self._task = None
        logger.info("operation recovery worker stopped worker=%s", self.worker_id)

    async def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("operation recovery scan failed worker=%s", self.worker_id)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._poll_interval_seconds
                )
            except TimeoutError:
                pass

    async def run_once(self) -> int:
        now = self._clock()
        async with self._session_factory() as session:
            claims = await OperationRepository(session).claim_due(
                lease_owner=self.worker_id,
                now=now,
                lease_expires_at=now + self._policy.lease_duration,
                limit=self._batch_size,
            )
            await session.commit()
        if not claims:
            return 0
        for claim in claims:
            logger.info(
                "operation claimed operation_id=%s worker=%s reclaimed=%s",
                claim.operation_id,
                self.worker_id,
                claim.reclaimed,
            )
        await asyncio.gather(*(self._recover(claim) for claim in claims))
        return len(claims)

    async def _recover(self, claim: OperationClaim) -> None:
        try:
            async with self._session_factory() as session:
                await OperationService(
                    session,
                    self._bus,
                    self._engine,
                    clock=self._clock,
                    recovery_policy=self._policy,
                ).reconcile_claimed(
                    claim.operation_id,
                    lease_owner=self.worker_id,
                )
        except OperationLeaseLostError:
            logger.warning(
                "operation recovery lease lost operation_id=%s worker=%s",
                claim.operation_id,
                self.worker_id,
            )
        except Exception:
            # The durable lease is deliberately left in place. If this process dies or
            # persistence fails, another worker can reclaim it after expiry.
            logger.exception(
                "operation reconciliation failed operation_id=%s worker=%s",
                claim.operation_id,
                self.worker_id,
            )
