from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from banking_api.domain.enums import ReportType
from banking_api.financial.report_models import (
    MonthlySpendingReport,
    ReportScope,
)


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    report_id: UUID
    report_type: ReportType
    report_version: int
    conversation_id: UUID
    source_task_id: UUID
    skill_id: str
    skill_version: int
    period: str
    source_snapshot_hash: str
    created_at: datetime
    account_names: dict[str, str] = Field(default_factory=dict)
    content: MonthlySpendingReport


class Report(ReportResponse):
    user_id: str


class ReportListItem(BaseModel):
    deleted_at: datetime | None = None
    report_id: UUID
    report_type: ReportType
    period: str
    headline: str
    total_spending_display: str
    scope: ReportScope
    conversation_id: UUID
    source_task_id: UUID
    created_at: datetime
