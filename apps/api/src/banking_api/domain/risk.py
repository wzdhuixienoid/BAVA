from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_serializer


class BusinessRiskLevel(StrEnum):
    """Per-request business risk, separate from static Tool permissions."""

    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class RiskReasonCode(StrEnum):
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

    @field_serializer(
        "daily_successful_total",
        "daily_in_flight_exposure",
        "requested_amount",
        "projected_daily_total",
        "threshold",
    )
    def serialize_decimal(self, value: Decimal) -> str:
        return format(value, "f")
