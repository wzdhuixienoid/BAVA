import json
import re

from pydantic import ValidationError

from banking_api.domain.enums import RequestedOutput
from banking_api.llm.models import LLMMessage, LLMRequest
from banking_api.llm.provider import LLMProvider, LLMProviderError
from banking_api.planning.constraints import has_conditional_control
from banking_api.routing.models import RequestRoute, RouteDecision

ROUTER_INSTRUCTIONS = """你是银行请求分类器。只输出一个 JSON 对象，格式为：
{"route":"MINIMAL_BANKING|FINANCIAL_ANALYSIS|TRANSFER_WORKFLOW|SUBSCRIPTION_ANALYSIS|SUBSCRIPTION_CANCEL|SUBSCRIPTION_RESUME|COMPLEX_PLAN|UNSUPPORTED","requested_output":"ANSWER|MONTHLY_REPORT|WORKFLOW","confidence":0.0}

路由规则：
- 账户列表、余额查询、可转账收款人列表、查询收款人、新增收款人页面指引 -> MINIMAL_BANKING / ANSWER
- 询问可以向谁转账属于只读收款人查询，不启动转账 Workflow
- 消费分析、月份支出、消费分类、花费原因、环比变化、最大消费 -> FINANCIAL_ANALYSIS / ANSWER
- 异常交易或奇怪扣款 -> FINANCIAL_ANALYSIS / ANSWER
- 生成、制作、给我一份月度或年度消费/账单报告 -> FINANCIAL_ANALYSIS / MONTHLY_REPORT
  兼容报告输出类型，期间可为 YYYY 或 YYYY-MM。
- 同时要求消费分析和生成报告 -> FINANCIAL_ANALYSIS / MONTHLY_REPORT
- 独立转账请求 -> TRANSFER_WORKFLOW / WORKFLOW
- 订阅列表、成本、涨价、即将续费 -> SUBSCRIPTION_ANALYSIS / ANSWER
- 取消某项订阅或代扣 -> SUBSCRIPTION_CANCEL / WORKFLOW
- 重新订阅、恢复某项订阅或代扣续费 -> SUBSCRIPTION_RESUME / WORKFLOW
- 需要两个以上已有高层能力协作且单个 Agent/Workflow 无法完整完成 -> COMPLEX_PLAN / ANSWER
- 先查余额再分析消费 -> COMPLEX_PLAN / ANSWER
- 先分析订阅再取消订阅 -> COMPLEX_PLAN / ANSWER
- 分析消费并生成报告仍由 FinancialAnalysis 完整完成，不拆计划
- 单纯取消订阅不等于订阅分析，单纯转账不等于查询余额
- 条件判断（余额、月消费、订阅月成本达到阈值）及条件后续动作 -> COMPLEX_PLAN / ANSWER
- 其他条件或 ELSE 请求也交给 COMPLEX_PLAN 确定性拒绝；循环及不支持业务不得执行
- 不含转账的分析请求如果包含其他不支持内容，只处理可支持的分析部分
- 投资、理财购买、卡片写操作或当前系统不支持的业务 -> UNSUPPORTED / ANSWER

MINIMAL_BANKING 和 UNSUPPORTED 的 requested_output 必须是 ANSWER。
TRANSFER_WORKFLOW、SUBSCRIPTION_CANCEL 和 SUBSCRIPTION_RESUME 必须是 WORKFLOW。

不要输出解释、Markdown 或推理过程。
""".strip()


class RoutingError(Exception):
    pass


class RequestRouter:
    def __init__(self, provider: LLMProvider, *, max_retries: int = 1) -> None:
        self._provider = provider
        self._max_retries = max_retries

    async def route(self, user_request: str) -> RouteDecision:
        normalized = "".join(user_request.casefold().split())
        if re.fullmatch(
            r"(?:请问|请|帮我查一下|查一下|查询)?我?(?:可以|能|可)?(?:向|给)"
            r"(?:谁|哪些人|哪些收款人|哪几个收款人)(?:转账|汇款|打款)(?:吗|呢)?[？?。！!]*",
            normalized,
        ):
            return RouteDecision(
                route=RequestRoute.MINIMAL_BANKING,
                requested_output=RequestedOutput.ANSWER,
                confidence=1.0,
            )
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
                normalized = "".join(user_request.casefold().split())
                if has_conditional_control(user_request):
                    return RouteDecision(
                        route=RequestRoute.COMPLEX_PLAN,
                        requested_output=RequestedOutput.ANSWER,
                        confidence=decision.confidence,
                    )
                if self._is_multi_capability_intent(user_request):
                    if decision.requested_output is RequestedOutput.MONTHLY_REPORT or (
                        "报告" in normalized
                        and any(marker in normalized for marker in ("生成", "制作", "一份"))
                    ):
                        return RouteDecision(
                            route=RequestRoute.UNSUPPORTED,
                            requested_output=RequestedOutput.ANSWER,
                            confidence=decision.confidence,
                        )
                    if decision.route is not RequestRoute.UNSUPPORTED:
                        return RouteDecision(
                            route=RequestRoute.COMPLEX_PLAN,
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
    def _is_multi_capability_intent(user_request: str) -> bool:
        normalized = "".join(user_request.casefold().split())
        has_transfer = any(marker in normalized for marker in ("转账", "汇款", "打款", "转给")) or (
            "给" in normalized and "转" in normalized
        )
        has_analysis = any(
            marker in normalized
            for marker in ("消费", "报告", "环比", "为什么花", "支出", "异常交易", "账单")
        )
        has_account = any(marker in normalized for marker in ("查余额", "余额", "有哪些账户"))
        has_sub_analysis = any(
            marker in normalized for marker in ("有哪些订阅", "看看订阅", "分析订阅")
        )
        has_resume = any(
            marker in normalized for marker in ("重新订阅", "恢复订阅", "恢复", "重新开通")
        ) and any(marker in normalized for marker in ("订阅", "星幕", "代扣", "续费", "会员"))
        has_cancel = "取消" in normalized and any(
            marker in normalized for marker in ("订阅", "星幕", "代扣")
        )
        return (
            sum((has_transfer, has_analysis, has_account, has_sub_analysis, has_cancel, has_resume))
            >= 2
        )
