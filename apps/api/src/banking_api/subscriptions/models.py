from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class BillingInterval(StrEnum):
    MONTHLY = "MONTHLY"
    ANNUAL = "ANNUAL"


class SubscriptionManagementType(StrEnum):
    MANAGED = "MANAGED"
    DETECTED_ONLY = "DETECTED_ONLY"


class SubscriptionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class SubscriptionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subscription_id: str | None = None
    merchant: str
    plan_name: str | None = None
    management_type: SubscriptionManagementType
    status: SubscriptionStatus
    billing_interval: BillingInterval
    last_charge_amount: Decimal
    currency: str
    last_charge_date: date
    next_billing_at: datetime | None = None
    next_billing_is_estimated: bool
    evidence_count: int = Field(ge=2)
    evidence_transaction_ids: list[str] = Field(max_length=6)
    price_change_amount: Decimal | None = None
    price_change_percent: Decimal | None = None
    cancellable: bool


class CurrencyCost(BaseModel):
    currency: str
    amount: Decimal


class DuplicateCandidate(BaseModel):
    merchant: str
    subscription_ids: list[str]


class SubscriptionAnalysisSnapshot(BaseModel):
    subscriptions: list[SubscriptionItem] = Field(max_length=50)
    monthly_cost_by_currency: list[CurrencyCost]
    annual_projected_cost_by_currency: list[CurrencyCost]
    upcoming_renewals: list[SubscriptionItem] = Field(max_length=20)
    price_changes: list[SubscriptionItem] = Field(max_length=20)
    duplicate_candidates: list[DuplicateCandidate]
    generated_at: datetime


class SubscriptionListOutput(BaseModel):
    snapshot: SubscriptionAnalysisSnapshot


class SubscriptionAnalysisInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upcoming_days: int = Field(default=7, ge=1, le=90)


class SubscriptionCancelOperationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str


class SubscriptionProviderOutput(BaseModel):
    outcome: str | None = None
    status: str | None = None
    provider_reference: str | None = None
    error_code: str | None = None
    error_message: str | None = None
