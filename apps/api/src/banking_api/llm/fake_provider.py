from collections.abc import Iterable

from banking_api.llm.models import LLMRequest, LLMResponse
from banking_api.llm.provider import LLMProviderError


class FakeLLMProvider:
    """Deterministic scripted provider used by automated tests."""

    def __init__(self, responses: Iterable[LLMResponse | Exception]) -> None:
        self._responses = list(responses)
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request.model_copy(deep=True))
        if not self._responses:
            raise LLMProviderError("FakeLLMProvider script exhausted", retryable=False)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response.model_copy(deep=True)
