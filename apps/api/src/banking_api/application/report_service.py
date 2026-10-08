import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.domain.enums import ReportType
from banking_api.domain.report import Report, ReportListItem
from banking_api.financial.analysis_snapshot import FinancialAnalysisSnapshot
from banking_api.financial.report_models import MonthlySpendingReport
from banking_api.persistence.models import ReportModel, TaskModel
from banking_api.persistence.repositories.reports import ReportRepository
from banking_api.skills.models import SkillDefinition


class ReportNotFoundError(Exception):
    pass


class ReportPersistenceError(Exception):
    pass


def source_snapshot_hash(snapshot: FinancialAnalysisSnapshot) -> str:
    canonical = json.dumps(
        snapshot.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class ReportService:
    def __init__(self, session: AsyncSession) -> None:
        self.reports = ReportRepository(session)

    async def create_report(
        self,
        *,
        user_id: str,
        conversation_id: UUID,
        source_task_id: UUID,
        report: MonthlySpendingReport,
        snapshot: FinancialAnalysisSnapshot,
        skill: SkillDefinition,
    ) -> Report:
        try:
            model = await self.reports.create_or_get(
                user_id=user_id,
                conversation_id=conversation_id,
                source_task_id=source_task_id,
                report_type=ReportType.MONTHLY_SPENDING,
                report_version=report.report_version,
                skill_id=skill.skill_id,
                skill_version=skill.version,
                period=report.period,
                content=report.model_dump(mode="json"),
                source_snapshot_hash=source_snapshot_hash(snapshot),
            )
        except Exception as exc:
            raise ReportPersistenceError("Report persistence failed") from exc
        return self._to_report(model)

    async def get_report_for_user(self, report_id: UUID, *, user_id: str) -> Report:
        model = await self.reports.get_for_user(report_id, user_id)
        if model is None:
            raise ReportNotFoundError
        return self._to_report(model)

    async def list_reports_for_user(
        self,
        *,
        user_id: str,
        conversation_id: UUID | None = None,
        limit: int = 20,
        offset: int = 0,
        deleted: bool = False,
    ) -> list[ReportListItem]:
        models = await self.reports.list_for_user(
            user_id=user_id,
            conversation_id=conversation_id,
            limit=limit,
            offset=offset,
            deleted=deleted,
        )
        return [self._to_list_item(model) for model in models]

    async def set_deleted(self, report_id: UUID, *, user_id: str, deleted: bool) -> None:
        model = await self.reports.get_for_user(
            report_id, user_id, include_deleted=True, for_update=True
        )
        if model is None:
            raise ReportNotFoundError
        if deleted and model.deleted_at is None:
            model.deleted_at = datetime.now(UTC)
        elif not deleted:
            model.deleted_at = None
        source_task = await self.reports.session.get(TaskModel, model.source_task_id)
        if source_task and source_task.user_id == user_id and source_task.output_json:
            if source_task.output_json.get("report_id") == str(report_id):
                source_task.output_json = {**source_task.output_json, "report_deleted": deleted}
        await self.reports.session.flush()

    @staticmethod
    def _to_report(model: ReportModel) -> Report:
        return Report(
            report_id=model.report_id,
            user_id=model.user_id,
            report_type=model.report_type,
            report_version=model.report_version,
            conversation_id=model.conversation_id,
            source_task_id=model.source_task_id,
            skill_id=model.skill_id,
            skill_version=model.skill_version,
            period=model.period,
            source_snapshot_hash=model.source_snapshot_hash,
            created_at=model.created_at,
            content=MonthlySpendingReport.model_validate(model.content_json),
        )

    @staticmethod
    def _to_list_item(model: ReportModel) -> ReportListItem:
        content = MonthlySpendingReport.model_validate(model.content_json)
        return ReportListItem(
            deleted_at=model.deleted_at,
            report_id=model.report_id,
            report_type=model.report_type,
            period=model.period,
            headline=content.headline,
            total_spending_display=content.overview.total_spending_display,
            scope=content.scope,
            conversation_id=model.conversation_id,
            source_task_id=model.source_task_id,
            created_at=model.created_at,
        )
