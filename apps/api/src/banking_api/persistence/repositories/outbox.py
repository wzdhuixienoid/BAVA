from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.persistence.models import EventModel, OutboxEventModel


@dataclass(frozen=True)
class OutboxClaim:
    outbox_id: UUID
    event_id: UUID
    lease_owner: str
    attempt: int
    reclaimed: bool


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enqueue(self, *, event_id: UUID, next_publish_at: datetime) -> OutboxEventModel:
        model = OutboxEventModel(
            event_id=event_id,
            next_publish_at=next_publish_at,
            publish_attempts=0,
        )
        self.session.add(model)
        await self.session.flush()
        return model

    async def claim_due(
        self,
        *,
        lease_owner: str,
        now: datetime,
        lease_expires_at: datetime,
        limit: int,
    ) -> list[OutboxClaim]:
        result = await self.session.execute(
            select(OutboxEventModel)
            .where(
                OutboxEventModel.published_at.is_(None),
                OutboxEventModel.next_publish_at.is_not(None),
                OutboxEventModel.next_publish_at <= now,
                or_(
                    OutboxEventModel.lease_expires_at.is_(None),
                    OutboxEventModel.lease_expires_at <= now,
                ),
            )
            .order_by(
                OutboxEventModel.next_publish_at,
                OutboxEventModel.created_at,
                OutboxEventModel.outbox_id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        claims: list[OutboxClaim] = []
        for model in result.scalars():
            reclaimed = model.lease_owner is not None and model.lease_expires_at is not None
            model.lease_owner = lease_owner
            model.lease_expires_at = lease_expires_at
            model.publish_attempts += 1
            claims.append(
                OutboxClaim(
                    outbox_id=model.outbox_id,
                    event_id=model.event_id,
                    lease_owner=lease_owner,
                    attempt=model.publish_attempts,
                    reclaimed=reclaimed,
                )
            )
        await self.session.flush()
        return claims

    async def get_claimed_event(
        self, *, outbox_id: UUID, lease_owner: str, lease_valid_at: datetime
    ) -> EventModel | None:
        result = await self.session.execute(
            select(EventModel)
            .join(OutboxEventModel, OutboxEventModel.event_id == EventModel.event_id)
            .where(
                OutboxEventModel.outbox_id == outbox_id,
                OutboxEventModel.published_at.is_(None),
                OutboxEventModel.lease_owner == lease_owner,
                OutboxEventModel.lease_expires_at > lease_valid_at,
            )
        )
        return result.scalar_one_or_none()

    async def mark_published(
        self,
        *,
        outbox_id: UUID,
        lease_owner: str,
        now: datetime,
    ) -> bool:
        result = await self.session.execute(
            update(OutboxEventModel)
            .where(
                OutboxEventModel.outbox_id == outbox_id,
                OutboxEventModel.published_at.is_(None),
                OutboxEventModel.lease_owner == lease_owner,
                OutboxEventModel.lease_expires_at > now,
            )
            .values(
                published_at=now,
                next_publish_at=None,
                lease_owner=None,
                lease_expires_at=None,
                last_error_code=None,
            )
        )
        return result.rowcount == 1  # type: ignore[attr-defined]

    async def schedule_retry(
        self,
        *,
        outbox_id: UUID,
        lease_owner: str,
        now: datetime,
        next_publish_at: datetime,
        error_code: str,
    ) -> bool:
        result = await self.session.execute(
            update(OutboxEventModel)
            .where(
                OutboxEventModel.outbox_id == outbox_id,
                OutboxEventModel.published_at.is_(None),
                OutboxEventModel.lease_owner == lease_owner,
                OutboxEventModel.lease_expires_at > now,
            )
            .values(
                next_publish_at=next_publish_at,
                lease_owner=None,
                lease_expires_at=None,
                last_error_code=error_code,
            )
        )
        return result.rowcount == 1  # type: ignore[attr-defined]
