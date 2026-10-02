from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from banking_api.financial.report_formatter import ReportFormatter


class TransactionAnomalyType(StrEnum):
    AMOUNT_SPIKE = "AMOUNT_SPIKE"
    RAPID_DUPLICATE = "RAPID_DUPLICATE"
    NEW_MERCHANT_HIGH_AMOUNT = "NEW_MERCHANT_HIGH_AMOUNT"
    SUBSCRIPTION_PRICE_SPIKE = "SUBSCRIPTION_PRICE_SPIKE"


class TransactionAnomalySeverity(StrEnum):
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class TransactionAnomalyEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_median: Decimal | None = None
    amount: Decimal | None = None
    ratio: Decimal | None = None
    sample_count: int | None = None
    merchant_seen_in_lookback: bool | None = None
    duplicate_count: int | None = None
    window_minutes: int | None = None
    previous_amount: Decimal | None = None
    current_amount: Decimal | None = None
    increase_percent: Decimal | None = None


class TransactionAnomalyItem(BaseModel):
    transaction_id: str
    occurred_at: datetime
    merchant_display: str
    amount: Decimal
    currency: str
    anomaly_types: list[TransactionAnomalyType]
    severity: TransactionAnomalySeverity
    reason_codes: list[str]
    evidence: dict[TransactionAnomalyType, TransactionAnomalyEvidence]
    related_transaction_ids: list[str] = Field(default_factory=list, max_length=10)
    amount_display: str = ""
    evidence_display: dict[TransactionAnomalyType, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def format_display(self):
        formatter = ReportFormatter()
        self.amount_display = formatter.money(self.amount, self.currency)
        labels = {
            "baseline_median": "历史中位数",
            "amount": "本笔金额",
            "ratio": "金额倍数",
            "sample_count": "历史样本数",
            "merchant_seen_in_lookback": "历史出现过商户",
            "duplicate_count": "重复扣费笔数",
            "window_minutes": "时间窗口（分钟）",
            "previous_amount": "上期金额",
            "current_amount": "本期金额",
            "increase_percent": "涨幅",
        }
        monetary = {"baseline_median", "amount", "previous_amount", "current_amount"}
        self.evidence_display = {}
        for rule, evidence in self.evidence.items():
            lines = []
            for field, value in evidence.model_dump().items():
                if value is None:
                    continue
                display = (
                    formatter.money(value, self.currency)
                    if field in monetary
                    else (
                        formatter.percentage_change(value)
                        if field == "increase_percent"
                        else "是"
                        if value is True
                        else "否"
                        if value is False
                        else str(value)
                    )
                )
                lines.append(f"{labels[field]}：{display}")
            self.evidence_display[rule] = lines
        return self


class TransactionAnomalySnapshot(BaseModel):
    user_scope: str
    analysis_period_started_at: datetime
    analysis_period_ended_at: datetime
    baseline_lookback_days: int
    insufficient_baseline: bool
    anomalies: list[TransactionAnomalyItem] = Field(max_length=50)
    generated_at: datetime


class TransactionAnomalyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_days: int = Field(default=30, ge=1, le=90)


class TransactionAnomalyOutput(BaseModel):
    snapshot: TransactionAnomalySnapshot
