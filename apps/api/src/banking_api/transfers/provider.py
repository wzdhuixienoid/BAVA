from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TransferProviderFaultMode(StrEnum):
    SUCCESS = "SUCCESS"
    DEFINITIVE_FAILURE = "DEFINITIVE_FAILURE"
    TIMEOUT_AFTER_ACCEPT = "TIMEOUT_AFTER_ACCEPT"


class TransferSubmissionOutcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    FAILED = "FAILED"


class TransferProviderStatusValue(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PENDING = "PENDING"
    UNKNOWN = "UNKNOWN"


class TransferProviderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    idempotency_key: UUID
    source_account_id: str
    payee_id: str
    amount: Decimal
    currency: str


class TransferSubmissionResult(BaseModel):
    outcome: TransferSubmissionOutcome
    provider_reference: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class TransferProviderStatus(BaseModel):
    status: TransferProviderStatusValue
    provider_reference: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class TransferProviderAmbiguousError(Exception):
    """The provider may have accepted the request, but no response was observed."""


class TransferProvider(Protocol):
    async def submit_transfer(
        self, request: TransferProviderRequest
    ) -> TransferSubmissionResult: ...

    async def get_transfer_status(
        self, *, user_id: str, idempotency_key: UUID, provider_reference: str | None
    ) -> TransferProviderStatus: ...
