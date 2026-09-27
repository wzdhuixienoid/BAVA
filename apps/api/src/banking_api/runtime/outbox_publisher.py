import asyncio
import logging
import os
import socket
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from banking_api.application.outbox_publication_policy import OutboxPublicationPolicy
from banking_api.persistence.repositories.outbox import OutboxClaim, OutboxRepository
from banking_api.runtime.event_bus import EventBus
from banking_api.runtime.event_publisher import to_event

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


class OutboxLeaseLostError(Exception):
    pass


class OutboxPublisher:
    """Delivers durable Event publication intents to the process-local EventBus."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bus: EventBus,
        *,
        policy: OutboxPublicationPolicy,
        poll_interval_seconds: float,
        batch_size: int,
        publisher_id: str | None = None,
        clock=_now,  # type: ignore[no-untyped-def]
    ) -> None:
        self._session_factory = session_factory
        self._bus = bus
        self._policy = policy
        self._poll_interval_seconds = poll_interval_seconds
        self._batch_size = batch_size
        self._clock = clock
        self.publisher_id = publisher_id or (
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
            self.run(), name=f"outbox-publisher:{self.publisher_id}"
        )
        logger.info("outbox publisher started publisher=%s", self.publisher_id)

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await self._task
            self._task = None
        logger.info("outbox publisher stopped publisher=%s", self.publisher_id)

    async def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("outbox publisher scan failed publisher=%s", self.publisher_id)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._poll_interval_seconds
                )
            except TimeoutError:
                pass

    async def run_once(self) -> int:
        now = self._clock()
        async with self._session_factory() as session:
            claims = await OutboxRepository(session).claim_due(
                lease_owner=self.publisher_id,
                now=now,
                lease_expires_at=now + self._policy.lease_duration,
                limit=self._batch_size,
            )
            await session.commit()
        if not claims:
            return 0
        for claim in claims:
            logger.info(
                "outbox row claimed outbox_id=%s event_id=%s publisher=%s attempt=%s "
                "reclaimed=%s",
                claim.outbox_id,
                claim.event_id,
                self.publisher_id,
                claim.attempt,
                claim.reclaimed,
            )
        # Every claim starts immediately; later batch rows do not wait sequentially
        # while their leases age.
        await asyncio.gather(*(self._publish_claim(claim) for claim in claims))
        return len(claims)

    async def _publish_claim(self, claim: OutboxClaim) -> None:
        event = await self._load_claimed_event(claim)
        logger.info(
            "outbox publish attempt outbox_id=%s event_id=%s event_type=%s attempt=%s",
            claim.outbox_id,
            claim.event_id,
            event.event_type,
            claim.attempt,
        )
        try:
            await self._bus.publish(to_event(event))
        except Exception:
            await self._schedule_retry(claim, error_code="EVENT_BUS_PUBLISH_FAILED")
            logger.exception(
                "outbox publish failed outbox_id=%s event_id=%s attempt=%s",
                claim.outbox_id,
                claim.event_id,
                claim.attempt,
            )
            return
        await self._mark_published(claim)
        logger.info(
            "outbox publish succeeded outbox_id=%s event_id=%s attempt=%s",
            claim.outbox_id,
            claim.event_id,
            claim.attempt,
        )

    async def _load_claimed_event(self, claim: OutboxClaim):  # type: ignore[no-untyped-def]
        now = self._clock()
        async with self._session_factory() as session:
            event = await OutboxRepository(session).get_claimed_event(
                outbox_id=claim.outbox_id,
                lease_owner=self.publisher_id,
                lease_valid_at=now,
            )
            await session.commit()
        if event is None:
            logger.warning(
                "outbox lease lost before publish outbox_id=%s event_id=%s publisher=%s",
                claim.outbox_id,
                claim.event_id,
                self.publisher_id,
            )
            raise OutboxLeaseLostError
        return event

    async def _mark_published(self, claim: OutboxClaim) -> None:
        now = self._clock()
        async with self._session_factory() as session:
            updated = await OutboxRepository(session).mark_published(
                outbox_id=claim.outbox_id,
                lease_owner=self.publisher_id,
                now=now,
            )
            if not updated:
                await session.rollback()
                logger.warning(
                    "outbox lease lost after publish outbox_id=%s event_id=%s publisher=%s",
                    claim.outbox_id,
                    claim.event_id,
                    self.publisher_id,
                )
                raise OutboxLeaseLostError
            await session.commit()

    async def _schedule_retry(self, claim: OutboxClaim, *, error_code: str) -> None:
        now = self._clock()
        next_publish_at = now + self._policy.retry_delay(claim.attempt)
        async with self._session_factory() as session:
            updated = await OutboxRepository(session).schedule_retry(
                outbox_id=claim.outbox_id,
                lease_owner=self.publisher_id,
                now=now,
                next_publish_at=next_publish_at,
                error_code=error_code,
            )
            if not updated:
                await session.rollback()
                logger.warning(
                    "outbox lease lost while scheduling retry outbox_id=%s event_id=%s "
                    "publisher=%s",
                    claim.outbox_id,
                    claim.event_id,
                    self.publisher_id,
                )
                raise OutboxLeaseLostError
            await session.commit()
        logger.info(
            "outbox retry scheduled outbox_id=%s event_id=%s attempt=%s "
            "next_publish_at=%s",
            claim.outbox_id,
            claim.event_id,
            claim.attempt,
            next_publish_at,
        )
