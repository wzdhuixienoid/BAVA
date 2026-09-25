from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.domain.enums import ReauthenticationStatus
from banking_api.domain.reauthentication import ReauthenticationMethod
from banking_api.persistence.models import ReauthenticationModel


class ReauthenticationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: str,
        workflow_id: UUID,
        approval_id: UUID,
        method: ReauthenticationMethod,
        provider_reference: str | None,
        expires_at: datetime,
    ) -> ReauthenticationModel:
        model = ReauthenticationModel(
            user_id=user_id,
            workflow_id=workflow_id,
            approval_id=approval_id,
            method=method,
            provider_reference=provider_reference,
            status=ReauthenticationStatus.PENDING,
            expires_at=expires_at,
            attempt_count=0,
        )
        self.session.add(model)
        await self.session.flush()
        return model

    async def get_for_workflow_user(
        self, reauth_id: UUID, workflow_id: UUID, user_id: str
    ) -> ReauthenticationModel | None:
        result = await self.session.execute(
            select(ReauthenticationModel).where(
                ReauthenticationModel.reauth_id == reauth_id,
                ReauthenticationModel.workflow_id == workflow_id,
                ReauthenticationModel.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def latest_for_workflow(
        self, workflow_id: UUID, user_id: str
    ) -> ReauthenticationModel | None:
        result = await self.session.execute(
            select(ReauthenticationModel)
            .where(
                ReauthenticationModel.workflow_id == workflow_id,
                ReauthenticationModel.user_id == user_id,
            )
            .order_by(ReauthenticationModel.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def invalidate_active(
        self, workflow_id: UUID, user_id: str, now: datetime
    ) -> list[ReauthenticationModel]:
        result = await self.session.execute(
            select(ReauthenticationModel).where(
                ReauthenticationModel.workflow_id == workflow_id,
                ReauthenticationModel.user_id == user_id,
                ReauthenticationModel.status.in_(
                    [
                        ReauthenticationStatus.PENDING,
                        ReauthenticationStatus.VERIFIED,
                    ]
                ),
            )
        )
        models = list(result.scalars())
        for model in models:
            model.status = ReauthenticationStatus.INVALIDATED
        await self.session.flush()
        return models
