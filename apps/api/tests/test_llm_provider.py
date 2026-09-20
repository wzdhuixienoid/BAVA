import json

import httpx

from banking_api.llm.models import LLMMessage, LLMRequest, LLMToolDefinition
from banking_api.llm.openai_compatible_provider import OpenAICompatibleProvider


async def test_openai_compatible_provider_maps_internal_models() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["Authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_balance",
                                        "arguments": '{"account_id":"acc_salary"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://llm.example/v1",
            api_key="secret-not-persisted",
            model="test-model",
            client=client,
        )
        response = await provider.generate(
            LLMRequest(
                messages=[LLMMessage(role="user", content="余额")],
                tools=[
                    LLMToolDefinition(
                        name="get_balance",
                        description="balance",
                        input_schema={"type": "object"},
                    )
                ],
            )
        )

    assert captured["authorization"] == "Bearer secret-not-persisted"
    assert captured["payload"] == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "余额"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get_balance",
                    "description": "balance",
                    "parameters": {"type": "object"},
                },
            }
        ],
        "tool_choice": "auto",
    }
    assert response.tool_calls[0].arguments == {"account_id": "acc_salary"}
    assert response.usage.total_tokens == 14
