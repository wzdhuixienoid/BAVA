import json
from typing import Any
from urllib.parse import urlsplit

import httpx

from banking_api.llm.models import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMToolCall,
    LLMUsage,
)
from banking_api.llm.provider import LLMProviderError


class OpenAICompatibleProvider:
    """The only adapter that knows the OpenAI-compatible wire format."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 30,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = self._normalize_api_root(base_url)
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._client = client

    @staticmethod
    def _normalize_api_root(base_url: str) -> str:
        normalized = base_url.strip().rstrip("/")
        if not normalized:
            return ""
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("LLM_BASE_URL must be an absolute HTTP(S) API root")
        if parsed.query or parsed.fragment:
            raise ValueError("LLM_BASE_URL must not contain a query string or fragment")
        if parsed.path.lower().endswith("/chat/completions"):
            raise ValueError(
                "LLM_BASE_URL must be the API root, not the /chat/completions endpoint"
            )
        return normalized

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if not self.base_url or not self.api_key or not self.model:
            raise LLMProviderError("LLM provider configuration is incomplete")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._message_to_wire(message) for message in request.messages],
        }
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                }
                for tool in request.tools
            ]
            payload["tool_choice"] = "auto"

        owns_client = self._client is None
        client = self._client
        try:
            if client is None:
                client = httpx.AsyncClient(
                    timeout=self.timeout_seconds,
                    trust_env=False,
                )
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            return self._response_from_wire(response.json())
        except (httpx.HTTPError, ImportError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMProviderError("OpenAI-compatible provider request failed") from exc
        finally:
            if owns_client and client is not None:
                await client.aclose()

    @staticmethod
    def _message_to_wire(message: LLMMessage) -> dict[str, Any]:
        item: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.reasoning_content is not None:
            item["reasoning_content"] = message.reasoning_content
        if message.tool_calls:
            item["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": call.arguments
                        if isinstance(call.arguments, str)
                        else json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        if message.tool_call_id is not None:
            item["tool_call_id"] = message.tool_call_id
        return item

    @staticmethod
    def _response_from_wire(payload: dict[str, Any]) -> LLMResponse:
        choice = payload["choices"][0]
        message = choice["message"]
        tool_calls = []
        for item in message.get("tool_calls") or []:
            raw_arguments = item["function"].get("arguments", "{}")
            try:
                arguments: Any = json.loads(raw_arguments)
            except (json.JSONDecodeError, TypeError):
                arguments = raw_arguments
            tool_calls.append(
                LLMToolCall(
                    id=item["id"],
                    name=item["function"]["name"],
                    arguments=arguments,
                )
            )
        usage = payload.get("usage") or {}
        return LLMResponse(
            content=message.get("content"),
            reasoning_content=message.get("reasoning_content"),
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason"),
            usage=LLMUsage(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
            ),
        )
