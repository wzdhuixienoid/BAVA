from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.persistence.models import IdentityMappingModel


class IdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_external_identity(
        self, *, issuer: str, subject: str
    ) -> IdentityMappingModel | None:
        result = await self.session.execute(
            select(IdentityMappingModel).where(
                IdentityMappingModel.issuer == issuer,
                IdentityMappingModel.subject == subject,
            )
        )
        return result.scalar_one_or_none()

    async def provision(self, *, user_id: str, issuer: str, subject: str) -> IdentityMappingModel:
        mapping = IdentityMappingModel(user_id=user_id, issuer=issuer, subject=subject)
        self.session.add(mapping)
        await self.session.flush()
        return mapping
