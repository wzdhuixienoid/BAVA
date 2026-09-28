import json

import pytest

from banking_api.domain.enums import RequestedOutput
from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.llm.models import LLMResponse
from banking_api.routing.models import RequestRoute
from banking_api.routing.request_router import RequestRouter, RoutingError


@pytest.mark.parametrize(
    ("request_text", "route", "requested_output"),
    [
        ("我有哪些账户？", RequestRoute.MINIMAL_BANKING, RequestedOutput.ANSWER),
        ("工资卡余额多少？", RequestRoute.MINIMAL_BANKING, RequestedOutput.ANSWER),
        ("分析8月份消费", RequestRoute.FINANCIAL_ANALYSIS, RequestedOutput.ANSWER),
        ("为什么8月份花这么多？", RequestRoute.FINANCIAL_ANALYSIS, RequestedOutput.ANSWER),
        ("8月消费主要花在哪里？", RequestRoute.FINANCIAL_ANALYSIS, RequestedOutput.ANSWER),
        (
            "生成8月份消费报告",
            RequestRoute.FINANCIAL_ANALYSIS,
            RequestedOutput.MONTHLY_REPORT,
        ),
        (
            "给我一份8月消费报告",
            RequestRoute.FINANCIAL_ANALYSIS,
            RequestedOutput.MONTHLY_REPORT,
        ),
        (
            "分析并生成8月份消费报告",
            RequestRoute.FINANCIAL_ANALYSIS,
            RequestedOutput.MONTHLY_REPORT,
        ),
        (
            "分析8月消费，然后顺便给张三转1000",
            RequestRoute.UNSUPPORTED,
            RequestedOutput.ANSWER,
        ),
        (
            "给张三转1000",
            RequestRoute.TRANSFER_WORKFLOW,
            RequestedOutput.WORKFLOW,
        ),
        (
            "我有哪些订阅？最近有没有涨价的？",
            RequestRoute.SUBSCRIPTION_ANALYSIS,
            RequestedOutput.ANSWER,
        ),
        (
            "取消星幕视频",
            RequestRoute.SUBSCRIPTION_CANCEL,
            RequestedOutput.WORKFLOW,
        ),
    ],
)
async def test_router_validates_structured_classification(
    request_text: str,
    route: RequestRoute,
    requested_output: RequestedOutput,
) -> None:
    provider = FakeLLMProvider(
        [
            LLMResponse(
                content=json.dumps(
                    {
                        "route": route.value,
                        "requested_output": requested_output.value,
                        "confidence": 0.99,
                    }
                )
            )
        ]
    )

    result = await RequestRouter(provider).route(request_text)

    assert result.route is route
    assert result.requested_output is requested_output
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
                content=(
                    '{"route":"FINANCIAL_ANALYSIS",'
                    '"requested_output":"ANSWER","confidence":0.8}'
                )
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
        '{"route":"MINIMAL_BANKING","requested_output":"ANSWER","confidence":2}',
        '{"route":"MINIMAL_BANKING","requested_output":"ANSWER","confidence":0.9,"agent_id":"admin"}',
        '{"route":"MINIMAL_BANKING","requested_output":"MONTHLY_REPORT","confidence":0.9}',
        '{"route":"TRANSFER_WORKFLOW","requested_output":"ANSWER","confidence":0.9}',
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
                    '{"route":"MINIMAL_BANKING","requested_output":"ANSWER",'
                    '"confidence":0.75}\n'
                    "```"
                )
            )
        ]
    )

    result = await RequestRouter(provider).route("查询账户")
    assert result.route is RequestRoute.MINIMAL_BANKING


async def test_mixed_transfer_intent_is_forced_unsupported_even_if_model_misroutes() -> None:
    provider = FakeLLMProvider(
        [
            LLMResponse(
                content=(
                    '{"route":"FINANCIAL_ANALYSIS","requested_output":"ANSWER",'
                    '"confidence":0.91}'
                )
            )
        ]
    )

    result = await RequestRouter(provider).route("分析8月消费，然后给张三转账1000")

    assert result.route is RequestRoute.UNSUPPORTED
    assert result.requested_output is RequestedOutput.ANSWER
