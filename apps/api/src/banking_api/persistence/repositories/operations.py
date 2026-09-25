from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.domain.enums import OperationStatus
from banking_api.domain.operation import OperationType
from banking_api.persistence.models import OperationModel, utc_now


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
    ) -> OperationModel | None:
        result = await self.session.execute(
            update(OperationModel)
            .where(
                OperationModel.operation_id == operation_id,
                OperationModel.user_id == user_id,
                OperationModel.version == expected_version,
            )
            .values(
                status=status,
                provider_reference=provider_reference,
                error_code=error_code,
                error_message=error_message,
                submitted_at=submitted_at,
                completed_at=completed_at,
                version=OperationModel.version + 1,
                updated_at=utc_now(),
            )
            .returning(OperationModel)
        )
        return result.scalar_one_or_none()
