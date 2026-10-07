from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from banking_api.domain.risk import TransferRiskDecision


class TransferIntent(BaseModel):
    """Semantic values only. Internal resource identifiers are deliberately absent."""

    model_config = ConfigDict(extra="forbid")

    recipient_query: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    source_account_hint: str | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def require_string_amount(cls, value: object) -> object:
        if value is not None and not isinstance(value, (str, Decimal)):
            raise ValueError("amount must be an exact decimal string")
        return value

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal | None) -> str | None:
        return None if value is None else format(value, "f")


class TransferDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_query: str | None = None
    payee_id: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    source_account_hint: str | None = None
    source_account_id: str | None = None

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal | None) -> str | None:
        return None if value is None else format(value, "f")


class TransferRequiredInputType(StrEnum):
    PAYEE_SELECTION = "PAYEE_SELECTION"
    SOURCE_ACCOUNT_SELECTION = "SOURCE_ACCOUNT_SELECTION"
    AMOUNT = "AMOUNT"
    RECIPIENT_QUERY = "RECIPIENT_QUERY"


class TransferRequiredInput(BaseModel):
    type: TransferRequiredInputType
    options: list[dict[str, Any]] = Field(default_factory=list, max_length=10)
    message: str


class TransferValidationIssue(BaseModel):
    code: str
    message: str


class TransferValidationResult(BaseModel):
    is_valid: bool
    validated_at: datetime
    available_balance: Decimal | None = None
    issues: list[TransferValidationIssue] = Field(default_factory=list)

    @field_serializer("available_balance")
    def serialize_balance(self, value: Decimal | None) -> str | None:
        return None if value is None else format(value, "f")


class TransferReviewPayload(BaseModel):
    source_account_id: str
    source_account_display_name: str
    source_account_masked_number: str
    payee_id: str
    payee_display_name: str
    payee_bank_name: str
    payee_masked_account: str
    amount: Decimal
    currency: str

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal) -> str:
        return format(value, "f")


class TransferAuthorizationSnapshot(BaseModel):
    approval_id: UUID
    approval_payload_hash: str
    approval_expires_at: datetime
    reauth_id: UUID | None = None
    reauth_verified_at: datetime | None = None
    reauth_expires_at: datetime | None = None


class TransferWorkflowState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft: TransferDraft
    required_input: TransferRequiredInput | None = None
    validation: TransferValidationResult | None = None
    review_payload: TransferReviewPayload | None = None
    risk_decision: TransferRiskDecision | None = None
    authorization: TransferAuthorizationSnapshot | None = None
    payee_options: list[dict[str, Any]] = Field(default_factory=list, max_length=10)
    source_account_options: list[dict[str, Any]] = Field(default_factory=list, max_length=10)


class SelectPayeeAction(BaseModel):
    payee_id: str = Field(min_length=1)
    expected_version: int = Field(ge=1)
    recipient_query: str | None = Field(default=None, min_length=1, max_length=100)


class SelectSourceAccountAction(BaseModel):
    account_id: str = Field(min_length=1)
    expected_version: int = Field(ge=1)


class SetAmountAction(BaseModel):
    amount: Decimal
    expected_version: int = Field(ge=1)

    @field_validator("amount", mode="before")
    @classmethod
    def require_string_amount(cls, value: object) -> object:
        if not isinstance(value, (str, Decimal)):
            raise ValueError("amount must be an exact decimal string")
        return value

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal) -> str:
        return format(value, "f")


class SetRecipientQueryAction(BaseModel):
    recipient_query: str = Field(min_length=1, max_length=100)
    expected_version: int = Field(ge=1)


class ApproveTransferAction(BaseModel):
    expected_version: int = Field(ge=1)


class StartReauthenticationAction(BaseModel):
    expected_version: int = Field(ge=1)


class VerifyReauthenticationAction(BaseModel):
    reauth_id: UUID
    verification_code: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=1)


class CancelWorkflowAction(BaseModel):
    expected_version: int = Field(ge=1)


class CommitTransferAction(BaseModel):
    expected_version: int = Field(ge=1)
