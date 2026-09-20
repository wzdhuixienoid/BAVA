from typing import Protocol

from banking_api.llm.models import LLMRequest, LLMResponse


class LLMProviderError(Exception):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class LLMProvider(Protocol):
    async def generate(self, request: LLMRequest) -> LLMResponse: ...
