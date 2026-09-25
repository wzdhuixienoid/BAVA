import hmac
from uuid import UUID

from banking_api.domain.reauthentication import ReauthenticationMethod
from banking_api.security.reauthentication.provider import ReauthenticationChallenge


class MockReauthenticationProvider:
    """Local/test provider. The configured secret is never returned or persisted."""

    def __init__(self, secret: str) -> None:
        self._secret = secret

    async def start_challenge(
        self, *, user_id: str, workflow_id: UUID, approval_id: UUID
    ) -> ReauthenticationChallenge:
        return ReauthenticationChallenge(method=ReauthenticationMethod.MOCK_CODE)

    async def verify(
        self,
        *,
        user_id: str,
        workflow_id: UUID,
        approval_id: UUID,
        provider_reference: str | None,
        verification_code: str,
    ) -> bool:
        return hmac.compare_digest(verification_code, self._secret)
