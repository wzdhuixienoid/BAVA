from enum import StrEnum

from pydantic import BaseModel

from banking_api.tools.models import PayeeSummary
from banking_api.workflows.subscription_cancel.models import SubscriptionCancelWorkflowState
from banking_api.workflows.transfer.models import TransferWorkflowState


class WorkflowStageStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_USER = "WAITING_USER"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class WorkflowStage(BaseModel):
    key: str
    label: str
    status: WorkflowStageStatus


class TransferAccountOption(BaseModel):
    account_id: str
    display_name: str
    masked_number: str
    currency: str
    available_balance_display: str


class WorkflowPresentation(BaseModel):
    business_success: bool
    approval_required: bool | None
    reauthentication_required: bool | None
    amount_display: str | None
    transfer_state: TransferWorkflowState | None = None
    subscription_state: SubscriptionCancelWorkflowState | None = None
    account_options: list[TransferAccountOption] = []
    payee_options: list[PayeeSummary] = []
    stages: list[WorkflowStage]
