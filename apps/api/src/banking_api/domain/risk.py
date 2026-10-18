from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_serializer, model_validator

from banking_api.financial.report_formatter import ReportFormatter


class BusinessRiskLevel(StrEnum):
    """Per-request business risk, separate from static Tool permissions."""

    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


# Existing cancellation policy; shared by Workflow DTO and persisted evidence.
SUBSCRIPTION_CANCEL_RISK_LEVEL = BusinessRiskLevel.YELLOW


class RiskReasonCode(StrEnum):
    PASSWORDLESS_LIMIT_REACHED = "PASSWORDLESS_LIMIT_REACHED"
    FUNDS_OUTFLOW_REQUIRES_REAUTH = "FUNDS_OUTFLOW_REQUIRES_REAUTH"
    READ_ONLY_AUTOMATIC = "READ_ONLY_AUTOMATIC"
    DAILY_TRANSFER_WITHIN_LIMIT = "DAILY_TRANSFER_WITHIN_LIMIT"
    DAILY_TRANSFER_LIMIT_EXCEEDED = "DAILY_TRANSFER_LIMIT_EXCEEDED"
    RISK_ESCALATED_AT_COMMIT = "RISK_ESCALATED_AT_COMMIT"
    RISK_NOT_DOWNGRADED = "RISK_NOT_DOWNGRADED"


class TransferRiskDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: BusinessRiskLevel
    required_approval: bool
    required_reauthentication: bool
    reason_codes: list[RiskReasonCode]
    business_date: date
    currency: str
    daily_successful_total: Decimal
    daily_in_flight_exposure: Decimal
    requested_amount: Decimal
    projected_daily_total: Decimal
    threshold: Decimal
    evaluated_at: datetime
    passwordless_limit: Decimal = Decimal("200.00")
    passwordless_limit_display: str = ""
    requested_amount_display: str = ""
    daily_successful_total_display: str = ""
    daily_in_flight_exposure_display: str = ""
    projected_daily_total_display: str = ""
    threshold_display: str = ""

    @model_validator(mode="after")
    def format_display(self):
        formatter = ReportFormatter()
        for field in (
            "requested_amount",
            "daily_successful_total",
            "daily_in_flight_exposure",
            "projected_daily_total",
            "threshold",
            "passwordless_limit",
        ):
            setattr(self, f"{field}_display", formatter.money(getattr(self, field), self.currency))
        return self

    @field_serializer(
        "daily_successful_total",
        "daily_in_flight_exposure",
        "requested_amount",
        "projected_daily_total",
        "threshold",
        "passwordless_limit",
    )
    def serialize_decimal(self, value: Decimal) -> str:
        return format(value, "f")
