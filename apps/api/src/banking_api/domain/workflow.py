from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from banking_api.domain.approval import ApprovalSummary
from banking_api.domain.enums import WorkflowStatus
from banking_api.domain.operation import OperationSummary
from banking_api.domain.reauthentication import ReauthenticationSummary
from banking_api.domain.risk import BusinessRiskLevel, TransferRiskDecision


class WorkflowType(StrEnum):
    TRANSFER = "TRANSFER"
    SUBSCRIPTION_CANCEL = "SUBSCRIPTION_CANCEL"


class Workflow(BaseModel):
    """Authoritative, user-owned persistent workflow resource."""

    model_config = ConfigDict(from_attributes=True)

    workflow_id: UUID
    user_id: str
    conversation_id: UUID
    source_task_id: UUID
    workflow_type: WorkflowType
    status: WorkflowStatus
    version: int
    state: dict[str, Any]
    risk_level: BusinessRiskLevel | None = None
    risk_decision: TransferRiskDecision | None = None
    approval_summary: ApprovalSummary | None = None
    reauth_summary: ReauthenticationSummary | None = None
    operation_summary: OperationSummary | None = None
    created_at: datetime
    updated_at: datetime
