from typing import Protocol
from uuid import UUID

from pydantic import BaseModel

from banking_api.domain.reauthentication import ReauthenticationMethod


class ReauthenticationChallenge(BaseModel):
    method: ReauthenticationMethod
    provider_reference: str | None = None


class ReauthenticationProvider(Protocol):
    async def start_challenge(
        self, *, user_id: str, workflow_id: UUID, approval_id: UUID
    ) -> ReauthenticationChallenge: ...

    async def verify(
        self,
        *,
        user_id: str,
        workflow_id: UUID,
        approval_id: UUID,
        provider_reference: str | None,
        verification_code: str,
    ) -> bool: ...
