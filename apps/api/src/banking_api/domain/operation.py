from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from banking_api.domain.enums import OperationStatus


class OperationType(StrEnum):
    WEALTH_PURCHASE = "WEALTH_PURCHASE"
    WEALTH_REDEEM = "WEALTH_REDEEM"
    TRANSFER = "TRANSFER"
    SUBSCRIPTION_CANCEL = "SUBSCRIPTION_CANCEL"
    SUBSCRIPTION_RESUME = "SUBSCRIPTION_RESUME"


class Operation(BaseModel):
    """Authoritative application-side record of one real side effect."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    operation_id: UUID
    user_id: str
    workflow_id: UUID
    approval_id: UUID
    operation_type: OperationType
    payload: dict[str, Any] = Field(validation_alias="payload_json")
    payload_hash: str
    idempotency_key: UUID
    status: OperationStatus
    version: int
    provider_reference: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    submitted_at: datetime | None = None
    completed_at: datetime | None = None
    next_reconcile_at: datetime | None = None
    reconcile_attempts: int = Field(ge=0)
    last_reconcile_at: datetime | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    updated_at: datetime


class OperationResource(BaseModel):
    """Frontend-safe operation resource; deliberately excludes key and payload."""

    operation_id: UUID
    workflow_id: UUID
    operation_type: OperationType
    status: OperationStatus
    version: int
    provider_reference: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    submitted_at: datetime | None = None
    completed_at: datetime | None = None
    next_reconcile_at: datetime | None = None
    reconcile_attempts: int = Field(ge=0)
    last_reconcile_at: datetime | None = None
    updated_at: datetime


class OperationSummary(BaseModel):
    operation_id: UUID
    status: OperationStatus
    provider_reference: str | None = None
    error_code: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class ReconcileOperationAction(BaseModel):
    expected_version: int = Field(ge=1)
