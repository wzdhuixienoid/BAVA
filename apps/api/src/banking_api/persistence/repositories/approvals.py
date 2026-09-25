from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.domain.approval import ApprovalType
from banking_api.domain.enums import ApprovalStatus
from banking_api.persistence.models import ApprovalModel


class ApprovalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_pending(
        self,
        *,
        user_id: str,
        workflow_id: UUID,
        payload: dict[str, Any],
        payload_hash: str,
        expires_at: datetime,
    ) -> ApprovalModel:
        model = ApprovalModel(
            user_id=user_id,
            workflow_id=workflow_id,
            approval_type=ApprovalType.TRANSFER,
            payload_json=payload,
            payload_hash=payload_hash,
            status=ApprovalStatus.PENDING,
            expires_at=expires_at,
        )
        self.session.add(model)
        await self.session.flush()
        return model

    async def get_for_workflow_user(
        self, approval_id: UUID, workflow_id: UUID, user_id: str
    ) -> ApprovalModel | None:
        result = await self.session.execute(
            select(ApprovalModel).where(
                ApprovalModel.approval_id == approval_id,
                ApprovalModel.workflow_id == workflow_id,
                ApprovalModel.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def latest_for_workflow(self, workflow_id: UUID, user_id: str) -> ApprovalModel | None:
        result = await self.session.execute(
            select(ApprovalModel)
            .where(
                ApprovalModel.workflow_id == workflow_id,
                ApprovalModel.user_id == user_id,
            )
            .order_by(ApprovalModel.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def invalidate_active(
        self, workflow_id: UUID, user_id: str, now: datetime
    ) -> list[ApprovalModel]:
        result = await self.session.execute(
            select(ApprovalModel).where(
                ApprovalModel.workflow_id == workflow_id,
                ApprovalModel.user_id == user_id,
                ApprovalModel.status.in_([ApprovalStatus.PENDING, ApprovalStatus.APPROVED]),
            )
        )
        models = list(result.scalars())
        for model in models:
            model.status = ApprovalStatus.INVALIDATED
            model.invalidated_at = now
        await self.session.flush()
        return models
