from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SubscriptionCancelIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subscription_query: str = Field(min_length=1, max_length=100)


class SubscriptionCancelDraft(SubscriptionCancelIntent):
    subscription_id: str | None = None


class SubscriptionCandidate(BaseModel):
    subscription_id: str | None
    merchant: str
    plan_name: str | None
    management_type: str
    status: str
    amount: Decimal
    currency: str


class SubscriptionCancelRequiredInputType(StrEnum):
    SUBSCRIPTION_SELECTION = "SUBSCRIPTION_SELECTION"


class SubscriptionCancelRequiredInput(BaseModel):
    type: SubscriptionCancelRequiredInputType
    message: str
    options: list[SubscriptionCandidate]


class SubscriptionCancelReviewPayload(BaseModel):
    action: str = "SUBSCRIPTION_CANCEL"
    subscription_id: str
    user_id: str
    merchant: str
    plan_name: str | None
    amount: Decimal
    currency: str
    next_billing_at: datetime | None


class SubscriptionCancelAuthorization(BaseModel):
    approval_id: UUID
    approval_payload_hash: str
    approval_expires_at: datetime


class SubscriptionCancelWorkflowState(BaseModel):
    draft: SubscriptionCancelDraft
    required_input: SubscriptionCancelRequiredInput | None = None
    candidates: list[SubscriptionCandidate] = []
    review_payload: SubscriptionCancelReviewPayload | None = None
    authorization: SubscriptionCancelAuthorization | None = None
    error_code: str | None = None
    error_message: str | None = None


class SelectSubscriptionAction(BaseModel):
    subscription_id: str
    expected_version: int = Field(ge=1)
