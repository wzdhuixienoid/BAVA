import json

from pydantic import ValidationError

from banking_api.llm.models import LLMMessage, LLMRequest
from banking_api.llm.provider import LLMProvider, LLMProviderError
from banking_api.routing.models import RouteDecision

ROUTER_INSTRUCTIONS = """你是银行请求分类器。只输出一个 JSON 对象，格式为：
{"route":"MINIMAL_BANKING|FINANCIAL_ANALYSIS|UNSUPPORTED","confidence":0.0}

路由规则：
- 账户列表、余额查询 -> MINIMAL_BANKING
- 消费分析、月份支出、消费分类、花费原因、环比变化、最大消费 -> FINANCIAL_ANALYSIS
- 同时包含消费分析和不支持的写操作 -> FINANCIAL_ANALYSIS，只处理可支持的分析部分
- 转账、投资、理财购买、卡片写操作或当前系统不支持的业务 -> UNSUPPORTED

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
                return RouteDecision.model_validate(payload)
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
