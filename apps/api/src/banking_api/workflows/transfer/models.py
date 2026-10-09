import unicodedata
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
)

from banking_api.domain.risk import TransferRiskDecision


def normalize_remark(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("remark must be text")
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError("remark cannot contain control characters")
    value = value.strip()
    if len(value) > 100:
        raise ValueError("remark must contain at most 100 Unicode characters")
    return value


Remark = Annotated[str, BeforeValidator(normalize_remark)]


class ExecutionTimeIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["SINGLE", "MONTHLY"] = "SINGLE"
    relative_days: int | None = Field(default=None, ge=-366, le=366)
    relative_minutes: int | None = Field(default=None, ge=-527040, le=527040)
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    month: int | None = Field(default=None, ge=1, le=12)
    day: int | None = Field(default=None, ge=1, le=31)
    weekday: int | None = Field(default=None, ge=1, le=7)
    week_offset: int | None = Field(default=None, ge=0, le=52)
    hour: int | None = Field(default=None, ge=0, le=23)
    minute: int | None = Field(default=None, ge=0, le=59)
    second: int | None = Field(default=None, ge=0, le=59)
    occurrence_count: int | None = Field(default=None, ge=2, le=12)
    ambiguous: bool = False


class MonthlyRecurrence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frequency: Literal["MONTHLY"] = "MONTHLY"
    day: int = Field(ge=1, le=31)
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    second: int = Field(default=0, ge=0, le=59)
    count: int = Field(ge=2, le=12)
    occurrences: list[datetime] = Field(min_length=2, max_length=12)


class TransferIntent(BaseModel):
    """Semantic values only. Internal resource identifiers are deliberately absent."""

    model_config = ConfigDict(extra="forbid")

    recipient_query: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    source_account_hint: str | None = None
    remark: Remark = ""
    execution_time_text: str | None = None
    time_intent: ExecutionTimeIntent | None = None

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
    remark: Remark = ""
    recurrence: MonthlyRecurrence | None = None
    recurrence_text: str | None = None
    schedule_requested: bool = False
    schedule_time_error: str | None = None
    scheduled_for: datetime | None = None
    execute_deadline: datetime | None = None
    business_timezone: str = "Asia/Shanghai"
    schedule_id: UUID | None = None
    aa_share_id: UUID | None = None

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal | None) -> str | None:
        return None if value is None else format(value, "f")


class TransferRequiredInputType(StrEnum):
    EXECUTION_TIME = "EXECUTION_TIME"
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
    recurrence: MonthlyRecurrence | None = None
    payee_target_version: str | None = None
    aa_request_id: UUID | None = None
    aa_share_id: UUID | None = None
    destination_user_id: str | None = None
    destination_account_id: str | None = None
    remark: Remark = ""
    scheduled_for: datetime | None = None
    execute_deadline: datetime | None = None
    business_timezone: str = "Asia/Shanghai"
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


class SetRemarkAction(BaseModel):
    remark: Remark
    expected_version: int = Field(ge=1)


class SetExecutionTimeAction(BaseModel):
    execution_time_text: str = Field(min_length=1, max_length=100)
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
