import json

import pytest

from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.llm.models import LLMResponse
from banking_api.routing.models import RequestRoute
from banking_api.routing.request_router import RequestRouter, RoutingError


@pytest.mark.parametrize(
    ("request_text", "route"),
    [
        ("我有哪些账户？", RequestRoute.MINIMAL_BANKING),
        ("工资卡余额多少？", RequestRoute.MINIMAL_BANKING),
        ("分析8月份消费", RequestRoute.FINANCIAL_ANALYSIS),
        ("为什么8月份花这么多？", RequestRoute.FINANCIAL_ANALYSIS),
        ("8月消费主要花在哪里？", RequestRoute.FINANCIAL_ANALYSIS),
        ("分析8月消费，然后顺便给张三转1000", RequestRoute.FINANCIAL_ANALYSIS),
        ("给张三转1000", RequestRoute.UNSUPPORTED),
    ],
)
async def test_router_validates_structured_classification(
    request_text: str, route: RequestRoute
) -> None:
    provider = FakeLLMProvider(
        [
            LLMResponse(
                content=json.dumps({"route": route.value, "confidence": 0.99})
            )
        ]
    )

    result = await RequestRouter(provider).route(request_text)

    assert result.route is route
    assert result.confidence == 0.99
    assert len(provider.requests) == 1
    assert provider.requests[0].tools == []
    assert provider.requests[0].messages[-1].content == request_text
    assert "不要输出解释" in (provider.requests[0].messages[0].content or "")
    assert "只处理可支持的分析部分" in (
        provider.requests[0].messages[0].content or ""
    )


async def test_router_retries_once_after_invalid_format() -> None:
    provider = FakeLLMProvider(
        [
            LLMResponse(content="not-json"),
            LLMResponse(
                content='{"route":"FINANCIAL_ANALYSIS","confidence":0.8}'
            ),
        ]
    )

    result = await RequestRouter(provider).route("分析8月消费")

    assert result.route is RequestRoute.FINANCIAL_ANALYSIS
    assert len(provider.requests) == 2


@pytest.mark.parametrize(
    "invalid",
    [
        '{"route":"WEALTH_ADVISOR","confidence":0.9}',
        '{"route":"MINIMAL_BANKING","confidence":2}',
        '{"route":"MINIMAL_BANKING","confidence":0.9,"agent_id":"admin"}',
    ],
)
async def test_router_fails_closed_after_two_invalid_decisions(invalid: str) -> None:
    provider = FakeLLMProvider([LLMResponse(content=invalid), LLMResponse(content=invalid)])

    with pytest.raises(RoutingError):
        await RequestRouter(provider).route("帮我处理请求")

    assert len(provider.requests) == 2


async def test_router_accepts_json_code_fence_without_free_reasoning() -> None:
    provider = FakeLLMProvider(
        [
            LLMResponse(
                content=(
                    "```json\n"
                    '{"route":"MINIMAL_BANKING","confidence":0.75}\n'
                    "```"
                )
            )
        ]
    )

    result = await RequestRouter(provider).route("查询账户")
    assert result.route is RequestRoute.MINIMAL_BANKING
