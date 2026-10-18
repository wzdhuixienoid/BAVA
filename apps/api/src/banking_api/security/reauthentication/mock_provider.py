import hmac
from uuid import UUID

from banking_api.domain.reauthentication import ReauthenticationMethod
from banking_api.security.reauthentication.provider import ReauthenticationChallenge


class MockReauthenticationProvider:
    """Local verification against the environment value; never return it to clients."""

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
        return hmac.compare_digest(verification_code.encode(), self._secret.encode())
