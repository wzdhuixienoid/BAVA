from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


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
