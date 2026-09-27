from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.domain.enums import OperationStatus
from banking_api.domain.operation import OperationType
from banking_api.persistence.models import OperationModel, utc_now

RECOVERABLE_OPERATION_STATUSES = (
    OperationStatus.CREATED,
    OperationStatus.SUBMITTED,
    OperationStatus.UNKNOWN,
)


@dataclass(frozen=True)
class OperationClaim:
    operation_id: UUID
    user_id: str
    status: OperationStatus
    version: int
    lease_owner: str
    reclaimed: bool


class OperationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_transfer(
        self,
        *,
        user_id: str,
        workflow_id: UUID,
        approval_id: UUID,
        payload: dict[str, Any],
        payload_hash: str,
        idempotency_key: UUID,
        next_reconcile_at: datetime,
    ) -> OperationModel:
        model = OperationModel(
            user_id=user_id,
            workflow_id=workflow_id,
            approval_id=approval_id,
            operation_type=OperationType.TRANSFER,
            payload_json=payload,
            payload_hash=payload_hash,
            idempotency_key=idempotency_key,
            status=OperationStatus.CREATED,
            version=1,
            next_reconcile_at=next_reconcile_at,
            reconcile_attempts=0,
        )
        self.session.add(model)
        await self.session.flush()
        return model

    async def get_for_user(
        self, operation_id: UUID, user_id: str, *, for_update: bool = False
    ) -> OperationModel | None:
        statement = select(OperationModel).where(
            OperationModel.operation_id == operation_id,
            OperationModel.user_id == user_id,
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def claim_due(
        self,
        *,
        lease_owner: str,
        now: datetime,
        lease_expires_at: datetime,
        limit: int,
    ) -> list[OperationClaim]:
        result = await self.session.execute(
            select(OperationModel)
            .where(
                OperationModel.status.in_(RECOVERABLE_OPERATION_STATUSES),
                or_(
                    OperationModel.next_reconcile_at.is_(None),
                    OperationModel.next_reconcile_at <= now,
                ),
                or_(
                    OperationModel.lease_expires_at.is_(None),
                    OperationModel.lease_expires_at <= now,
                ),
            )
            .order_by(
                OperationModel.next_reconcile_at.asc().nulls_first(),
                OperationModel.created_at,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        claims: list[OperationClaim] = []
        for operation in result.scalars():
            reclaimed = operation.lease_expires_at is not None
            operation.lease_owner = lease_owner
            operation.lease_expires_at = lease_expires_at
            claims.append(
                OperationClaim(
                    operation_id=operation.operation_id,
                    user_id=operation.user_id,
                    status=operation.status,
                    version=operation.version,
                    lease_owner=lease_owner,
                    reclaimed=reclaimed,
                )
            )
        await self.session.flush()
        return claims

    async def get_claimed(
        self,
        operation_id: UUID,
        lease_owner: str,
        *,
        lease_valid_at: datetime,
        for_update: bool = False,
    ) -> OperationModel | None:
        statement = select(OperationModel).where(
            OperationModel.operation_id == operation_id,
            OperationModel.lease_owner == lease_owner,
            OperationModel.lease_expires_at > lease_valid_at,
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_for_workflow(
        self, workflow_id: UUID, user_id: str
    ) -> OperationModel | None:
        result = await self.session.execute(
            select(OperationModel).where(
                OperationModel.workflow_id == workflow_id,
                OperationModel.user_id == user_id,
                OperationModel.operation_type == OperationType.TRANSFER,
            )
        )
        return result.scalar_one_or_none()

    async def update_if_version(
        self,
        *,
        operation_id: UUID,
        user_id: str,
        expected_version: int,
        status: OperationStatus,
        provider_reference: str | None,
        error_code: str | None,
        error_message: str | None,
        submitted_at: datetime | None,
        completed_at: datetime | None,
        lease_owner: str,
        reconcile_attempts: int,
        last_reconcile_at: datetime | None,
        next_reconcile_at: datetime | None,
        release_lease: bool,
        lease_valid_at: datetime,
        retained_lease_expires_at: datetime,
    ) -> OperationModel | None:
        result = await self.session.execute(
            update(OperationModel)
            .execution_options(synchronize_session=False, populate_existing=True)
            .where(
                OperationModel.operation_id == operation_id,
                OperationModel.user_id == user_id,
                OperationModel.version == expected_version,
                OperationModel.lease_owner == lease_owner,
                OperationModel.lease_expires_at > lease_valid_at,
            )
            .values(
                status=status,
                provider_reference=provider_reference,
                error_code=error_code,
                error_message=error_message,
                submitted_at=submitted_at,
                completed_at=completed_at,
                reconcile_attempts=reconcile_attempts,
                last_reconcile_at=last_reconcile_at,
                next_reconcile_at=next_reconcile_at,
                lease_owner=None if release_lease else lease_owner,
                lease_expires_at=None if release_lease else retained_lease_expires_at,
                version=OperationModel.version + 1,
                updated_at=utc_now(),
            )
            .returning(OperationModel)
        )
        return result.scalar_one_or_none()
