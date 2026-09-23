from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.domain.enums import ReportType
from banking_api.persistence.models import ReportModel


class ReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_or_get(
        self,
        *,
        user_id: str,
        conversation_id: UUID,
        source_task_id: UUID,
        report_type: ReportType,
        report_version: int,
        skill_id: str,
        skill_version: int,
        period: str,
        content: dict[str, object],
        source_snapshot_hash: str,
    ) -> ReportModel:
        existing = await self.get_by_source(
            source_task_id=source_task_id,
            report_type=report_type,
            report_version=report_version,
        )
        if existing is not None:
            return existing
        model = ReportModel(
            user_id=user_id,
            conversation_id=conversation_id,
            source_task_id=source_task_id,
            report_type=report_type,
            report_version=report_version,
            skill_id=skill_id,
            skill_version=skill_version,
            period=period,
            content_json=content,
            source_snapshot_hash=source_snapshot_hash,
        )
        self.session.add(model)
        try:
            await self.session.flush()
            return model
        except IntegrityError:
            await self.session.rollback()
            existing = await self.get_by_source(
                source_task_id=source_task_id,
                report_type=report_type,
                report_version=report_version,
            )
            if existing is None:
                raise
            return existing

    async def get_by_source(
        self,
        *,
        source_task_id: UUID,
        report_type: ReportType,
        report_version: int,
    ) -> ReportModel | None:
        result = await self.session.execute(
            select(ReportModel).where(
                ReportModel.source_task_id == source_task_id,
                ReportModel.report_type == report_type,
                ReportModel.report_version == report_version,
            )
        )
        return result.scalar_one_or_none()

    async def get_for_user(self, report_id: UUID, user_id: str) -> ReportModel | None:
        result = await self.session.execute(
            select(ReportModel).where(
                ReportModel.report_id == report_id,
                ReportModel.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        *,
        user_id: str,
        conversation_id: UUID | None,
        limit: int,
        offset: int,
    ) -> list[ReportModel]:
        statement = select(ReportModel).where(ReportModel.user_id == user_id)
        if conversation_id is not None:
            statement = statement.where(
                ReportModel.conversation_id == conversation_id
            )
        result = await self.session.execute(
            statement.order_by(ReportModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars())
