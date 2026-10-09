import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select

from banking_api.application.operation_service import OperationActionError, OperationService
from banking_api.application.schedule_service import ScheduleService
from banking_api.config.settings import get_settings
from banking_api.persistence.models import ScheduledTransferModel, WorkflowModel
from banking_api.security.guard import SecurityWriteLockedError

logger = logging.getLogger(__name__)


class ScheduleWorker:
    def __init__(
        self, session_factory, bus, engine, *, worker_id=None, clock=lambda: datetime.now(UTC)
    ):
        self.factory, self.bus, self.engine, self.clock = session_factory, bus, engine, clock
        self.worker_id = worker_id or f"schedule:{uuid4()}"
        self.stop_event = asyncio.Event()
        self.task = None

    def start(self):
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        self.stop_event.set()
        if self.task:
            await self.task

    async def run(self):
        while not self.stop_event.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("schedule scan failed")
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=2)
            except TimeoutError:
                pass

    async def run_once(self):
        now = self.clock()
        async with self.factory() as session:
            rows = (
                await session.scalars(
                    select(ScheduledTransferModel)
                    .where(
                        ScheduledTransferModel.operation_id.is_(None),
                        ScheduledTransferModel.scheduled_for <= now,
                        or_(
                            ScheduledTransferModel.status == "SCHEDULED",
                            and_(
                                ScheduledTransferModel.status == "EXECUTING",
                                ScheduledTransferModel.lease_expires_at <= now,
                            ),
                        ),
                    )
                    .order_by(ScheduledTransferModel.scheduled_for)
                    .limit(20)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            claims = []
            for row in rows:
                row.version += 1
                if (
                    row.execute_deadline < now
                    if row.execute_deadline.tzinfo
                    else row.execute_deadline.replace(tzinfo=UTC) < now
                ):
                    row.status, row.error_code = "EXPIRED", "SCHEDULE_EXECUTION_WINDOW_EXPIRED"
                    await ScheduleService(session, self.engine)._event(row, "schedule.expired")
                else:
                    row.status, row.lease_owner = "EXECUTING", self.worker_id
                    row.lease_expires_at = now + timedelta(
                        seconds=get_settings().scheduled_transfer_lease_seconds
                    )
                    claims.append((row.schedule_id, row.workflow_id, row.user_id))
            await session.commit()
        for schedule_id, workflow_id, user_id in claims:
            try:
                async with self.factory() as session:
                    workflow = await session.get(WorkflowModel, workflow_id)
                    service = OperationService(session, self.bus, self.engine, clock=self.clock)
                    operation = await service.prepare_transfer(
                        workflow_id,
                        user_id=user_id,
                        expected_version=workflow.version,
                        schedule_id=schedule_id,
                        lease_owner=self.worker_id,
                    )
                    await service.reconcile(
                        operation.operation_id, user_id=user_id, expected_version=operation.version
                    )
            except (OperationActionError, SecurityWriteLockedError) as exc:
                async with self.factory() as session:
                    row = await ScheduleService(session, self.engine)._owned(
                        schedule_id, user_id, lock=True
                    )
                    if (
                        row.operation_id is None
                        and row.status == "EXECUTING"
                        and row.lease_owner == self.worker_id
                    ):
                        row.status, row.error_code = "FAILED", str(exc)[:100]
                        row.lease_owner, row.lease_expires_at = None, None
                        row.version += 1
                        await ScheduleService(session, self.engine)._event(row, "schedule.failed")
                        await session.commit()
            except Exception:
                # Leave a durable lease for restart recovery; never create another Operation.
                logger.exception("schedule execution interrupted schedule=%s", schedule_id)
        return len(rows)
