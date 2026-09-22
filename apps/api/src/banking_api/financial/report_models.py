from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DataQualityStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


class ReportInsightType(StrEnum):
    STRUCTURE = "STRUCTURE"
    CHANGE = "CHANGE"
    TRANSACTION = "TRANSACTION"
    DATA_QUALITY = "DATA_QUALITY"


class ReportScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_ids: list[str]


class ReportOverview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_income: Decimal
    total_income_display: str
    total_spending: Decimal
    total_spending_display: str
    transaction_count: int
    currency: str


class ReportPeriodComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    previous_period: str
    previous_spending: Decimal
    previous_spending_display: str
    absolute_change: Decimal
    absolute_change_display: str
    percentage_change: Decimal | None
    percentage_change_display: str


class ReportCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    amount: Decimal
    amount_display: str
    transaction_count: int
    share: Decimal
    share_display: str
    previous_amount: Decimal | None = None
    previous_amount_display: str | None = None
    absolute_change: Decimal | None = None
    absolute_change_display: str | None = None
    percentage_change: Decimal | None = None
    percentage_change_display: str | None = None


class ReportTopTransaction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str
    merchant: str
    description: str
    category: str
    amount: Decimal
    amount_display: str
    occurred_at: datetime
    account_id: str


class ReportDataQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: DataQualityStatus
    notes: list[str] = Field(default_factory=list)


class ReportInsight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ReportInsightType
    title: str = Field(min_length=1)
    narrative: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)

    @field_validator("title", "narrative")
    @classmethod
    def non_blank_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("text must not be blank")
        return stripped


class ReportNarrativeDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(min_length=1)
    insights: list[ReportInsight] = Field(min_length=2, max_length=5)

    @field_validator("headline")
    @classmethod
    def non_blank_headline(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("headline must not be blank")
        return stripped


class MonthlySpendingReportCore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version: int = 1
    period: str
    scope: ReportScope
    overview: ReportOverview
    period_comparison: ReportPeriodComparison | None
    category_breakdown: list[ReportCategory]
    top_transactions: list[ReportTopTransaction]
    data_quality: ReportDataQuality


class MonthlySpendingReport(MonthlySpendingReportCore):
    headline: str
    insights: list[ReportInsight]
