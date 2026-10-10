from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from banking_api.domain.enums import ApprovalStatus


class ApprovalType(StrEnum):
    WEALTH_PURCHASE = "WEALTH_PURCHASE"
    WEALTH_REDEEM = "WEALTH_REDEEM"
    TRANSFER = "TRANSFER"
    SUBSCRIPTION_CANCEL = "SUBSCRIPTION_CANCEL"
    SUBSCRIPTION_RESUME = "SUBSCRIPTION_RESUME"


class Approval(BaseModel):
    """Single canonical-payload approval with atomic operation consumption."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    approval_id: UUID
    user_id: str
    workflow_id: UUID
    approval_type: ApprovalType
    payload: dict[str, Any] = Field(validation_alias="payload_json")
    payload_hash: str
    status: ApprovalStatus
    expires_at: datetime
    approved_at: datetime | None = None
    invalidated_at: datetime | None = None
    consumed_at: datetime | None = None
    consumed_by_operation_id: UUID | None = None
    created_at: datetime


class ApprovalSummary(BaseModel):
    approval_id: UUID
    status: ApprovalStatus
    expires_at: datetime
