from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from banking_api.financial.report_formatter import ReportFormatter


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
    last_charge_date: date | None
    next_billing_at: datetime | None = None
    next_billing_is_estimated: bool
    evidence_count: int = Field(ge=0)
    evidence_transaction_ids: list[str] = Field(max_length=6)
    price_change_amount: Decimal | None = None
    price_change_percent: Decimal | None = None
    cancellable: bool
    resumable: bool = False
    contract_version: int = 0
    contract_amount: Decimal | None = None
    billing_anchor_at: datetime | None = None
    contract_amount_display: str | None = None
    last_charge_display: str = ""
    price_change_display: str | None = None
    price_change_percent_display: str | None = None
    monthly_cost: Decimal = Decimal("0")
    annual_projected_cost: Decimal = Decimal("0")
    monthly_cost_display: str = ""
    annual_projected_cost_display: str = ""

    @model_validator(mode="after")
    def format_display(self):
        formatter = ReportFormatter()
        self.contract_amount_display = (
            formatter.money(self.contract_amount, self.currency)
            if self.contract_amount is not None
            else None
        )
        self.last_charge_display = formatter.money(self.last_charge_amount, self.currency)
        self.price_change_display = (
            formatter.money_change(self.price_change_amount, self.currency)
            if self.price_change_amount is not None
            else None
        )
        self.price_change_percent_display = (
            formatter.percentage_change(self.price_change_percent)
            if self.price_change_percent is not None
            else None
        )
        self.monthly_cost_display = formatter.money(self.monthly_cost, self.currency)
        self.annual_projected_cost_display = formatter.money(
            self.annual_projected_cost, self.currency
        )
        return self


class CurrencyCost(BaseModel):
    currency: str
    amount: Decimal
    amount_display: str = ""

    @model_validator(mode="after")
    def format_display(self):
        self.amount_display = ReportFormatter().money(self.amount, self.currency)
        return self


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
