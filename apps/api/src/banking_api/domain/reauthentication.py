from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from banking_api.domain.enums import ReauthenticationStatus


class ReauthenticationMethod(StrEnum):
    MOCK_CODE = "MOCK_CODE"
    TOTP = "TOTP"


class Reauthentication(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    reauth_id: UUID
    user_id: str
    workflow_id: UUID
    approval_id: UUID
    method: ReauthenticationMethod
    status: ReauthenticationStatus
    provider_reference: str | None = None
    expires_at: datetime
    verified_at: datetime | None = None
    attempt_count: int
    created_at: datetime


class ReauthenticationSummary(BaseModel):
    reauth_id: UUID
    status: ReauthenticationStatus
    method: ReauthenticationMethod
    expires_at: datetime
