import json

from pydantic import ValidationError

from banking_api.domain.enums import RequestedOutput
from banking_api.llm.models import LLMMessage, LLMRequest
from banking_api.llm.provider import LLMProvider, LLMProviderError
from banking_api.routing.models import RequestRoute, RouteDecision

ROUTER_INSTRUCTIONS = """你是银行请求分类器。只输出一个 JSON 对象，格式为：
{"route":"MINIMAL_BANKING|FINANCIAL_ANALYSIS|TRANSFER_WORKFLOW|UNSUPPORTED","requested_output":"ANSWER|MONTHLY_REPORT|WORKFLOW","confidence":0.0}

路由规则：
- 账户列表、余额查询 -> MINIMAL_BANKING / ANSWER
- 消费分析、月份支出、消费分类、花费原因、环比变化、最大消费 -> FINANCIAL_ANALYSIS / ANSWER
- 生成、制作、给我一份月度消费报告 -> FINANCIAL_ANALYSIS / MONTHLY_REPORT
- 同时要求消费分析和生成报告 -> FINANCIAL_ANALYSIS / MONTHLY_REPORT
- 独立转账请求 -> TRANSFER_WORKFLOW / WORKFLOW
- 转账与分析、报告或其他意图混合 -> UNSUPPORTED / ANSWER，不处理任何一部分
- 不含转账的分析请求如果包含其他不支持内容，只处理可支持的分析部分
- 投资、理财购买、卡片写操作或当前系统不支持的业务 -> UNSUPPORTED / ANSWER

MINIMAL_BANKING 和 UNSUPPORTED 的 requested_output 必须是 ANSWER。
TRANSFER_WORKFLOW 必须是 WORKFLOW。

不要输出解释、Markdown 或推理过程。
""".strip()


class RoutingError(Exception):
    pass


class RequestRouter:
    def __init__(self, provider: LLMProvider, *, max_retries: int = 1) -> None:
        self._provider = provider
        self._max_retries = max_retries

    async def route(self, user_request: str) -> RouteDecision:
        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content=ROUTER_INSTRUCTIONS),
                LLMMessage(role="user", content=user_request),
            ]
        )
        for _ in range(self._max_retries + 1):
            try:
                response = await self._provider.generate(request)
                if response.tool_calls or not response.content:
                    continue
                payload = self._parse_json(response.content)
                decision = RouteDecision.model_validate(payload)
                if self._is_mixed_transfer_intent(user_request):
                    return RouteDecision(
                        route=RequestRoute.UNSUPPORTED,
                        requested_output=RequestedOutput.ANSWER,
                        confidence=decision.confidence,
                    )
                return decision
            except (json.JSONDecodeError, ValidationError, TypeError, LLMProviderError):
                continue
        raise RoutingError("Router did not return a valid structured decision")

    @staticmethod
    def _parse_json(content: str) -> object:
        candidate = content.strip()
        if candidate.startswith("```json") and candidate.endswith("```"):
            candidate = candidate[7:-3].strip()
        elif candidate.startswith("```") and candidate.endswith("```"):
            candidate = candidate[3:-3].strip()
        return json.loads(candidate)

    @staticmethod
    def _is_mixed_transfer_intent(user_request: str) -> bool:
        normalized = "".join(user_request.casefold().split())
        has_transfer = any(
            marker in normalized for marker in ("转账", "汇款", "打款", "转给")
        ) or ("给" in normalized and "转" in normalized)
        has_analysis = any(
            marker in normalized
            for marker in ("分析", "消费", "报告", "环比", "为什么花")
        )
        return has_transfer and has_analysis
