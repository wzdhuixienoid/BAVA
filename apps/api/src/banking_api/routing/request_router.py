import json
import re

from pydantic import ValidationError

from banking_api.domain.enums import RequestedOutput
from banking_api.llm.models import LLMMessage, LLMRequest
from banking_api.llm.provider import LLMProvider, LLMProviderError
from banking_api.planning.constraints import has_conditional_control
from banking_api.routing.models import RequestRoute, RouteDecision

ROUTER_INSTRUCTIONS = """你是银行请求分类器。只输出一个 JSON 对象，格式为：
{"route":"WEALTH_ANALYSIS|WEALTH_PURCHASE|WEALTH_REDEEM|ACCOUNT_QUERY|FINANCIAL_ANALYSIS|PERSONAL_BANKING|AA_COLLECTION|TRANSFER_WORKFLOW|SUBSCRIPTION_ANALYSIS|SUBSCRIPTION_CANCEL|SUBSCRIPTION_RESUME|COMPLEX_PLAN|UNSUPPORTED","requested_output":"ANSWER|MONTHLY_REPORT|WORKFLOW","confidence":0.0}

路由规则：
- 账户列表、余额查询、可转账收款人列表、查询收款人、新增收款人页面指引 -> ACCOUNT_QUERY / ANSWER
- 询问可以向谁转账属于只读收款人查询，不启动转账 Workflow
- 最近有哪些转账、转入转出历史、账单/购物明细、订阅实际扣费和理财现金流水 -> ACCOUNT_QUERY / ANSWER
- 查历史流水与发起交易必须区分；查询已转账记录不启动转账，不调用推进状态的工具
- 转账总额、按收款人分析/汇总、最近转给谁多少钱 -> ACCOUNT_QUERY / ANSWER
  账单工具summary已提供完整统计。
- 历史流水加消费统计/报告 -> PERSONAL_BANKING；先查流水再转账等写操作组合 -> COMPLEX_PLAN
- 消费分析、月份支出、消费分类、花费原因、环比变化、最大消费 -> FINANCIAL_ANALYSIS / ANSWER
- 异常交易或奇怪扣款 -> FINANCIAL_ANALYSIS / ANSWER
- 生成、制作、给我一份月度或年度消费/账单报告 -> FINANCIAL_ANALYSIS / MONTHLY_REPORT
  兼容报告输出类型，期间可为 YYYY 或 YYYY-MM。
- 同时要求消费分析和生成报告 -> FINANCIAL_ANALYSIS / MONTHLY_REPORT
- 拆分 AA、聚餐平摊收款请求 -> AA_COLLECTION / WORKFLOW；创建收款请求不等于付款
- 即时、单次预约和按月周期转账请求均属于独立转账；按月转账不是条件循环计划
- 独立转账请求 -> TRANSFER_WORKFLOW / WORKFLOW
- 订阅列表、成本、涨价、即将续费 -> SUBSCRIPTION_ANALYSIS / ANSWER
- 取消某项订阅或代扣 -> SUBSCRIPTION_CANCEL / WORKFLOW
- 重新订阅、恢复某项订阅或代扣续费 -> SUBSCRIPTION_RESUME / WORKFLOW
- 需要两个以上已有高层能力协作且单个 Agent/Workflow 无法完整完成 -> COMPLEX_PLAN / ANSWER
- 账户或余额查询加消费分析的只读组合 -> PERSONAL_BANKING / ANSWER
- 查询余额并生成消费报告 -> PERSONAL_BANKING / MONTHLY_REPORT
- 先分析订阅再取消订阅 -> COMPLEX_PLAN / ANSWER
- 分析消费并生成报告仍由 FinancialAnalysis 完整完成，不拆计划
- 单纯取消订阅不等于订阅分析，单纯转账不等于查询余额
- 条件判断（余额、月消费、订阅月成本达到阈值）及条件后续动作 -> COMPLEX_PLAN / ANSWER
- 其他条件或 ELSE 请求也交给 COMPLEX_PLAN 确定性拒绝；循环及不支持业务不得执行
- 不含转账的分析请求如果包含其他不支持内容，只处理可支持的分析部分
- 理财产品、对比、推荐、说明书、持仓、订单查询 -> WEALTH_ANALYSIS / ANSWER
- 想买理财、只说产品名或询问完成测评后能否购买 -> WEALTH_ANALYSIS / ANSWER，先介绍产品及购买入口
- 明确指定产品、本人付款账户及数量的独立申购 -> WEALTH_PURCHASE / WORKFLOW
- 独立理财赎回 -> WEALTH_REDEEM / WORKFLOW
- 条件自动投资、多笔理财或理财与其他写业务组合 -> UNSUPPORTED / ANSWER
- 卡片写操作或当前系统不支持的业务 -> UNSUPPORTED / ANSWER

ACCOUNT_QUERY 和 UNSUPPORTED 的 requested_output 必须是 ANSWER。
AA_COLLECTION、TRANSFER_WORKFLOW、SUBSCRIPTION_CANCEL 和 SUBSCRIPTION_RESUME 必须是 WORKFLOW。

不要输出解释、Markdown 或推理过程。
""".strip()


class RoutingError(Exception):
    pass


class RequestRouter:
    def __init__(self, provider: LLMProvider, *, max_retries: int = 1) -> None:
        self._provider = provider
        self._max_retries = max_retries

    async def route(
        self, user_request: str, *, wealth_context: dict | None = None
    ) -> RouteDecision:
        from banking_api.config.settings import get_settings
        from banking_api.wealth.context import ASSESSMENT_UPDATE, EDUCATION, FOLLOW_UP

        # Complete explicit buys take precedence over contextual FOLLOW_UP keywords.
        from banking_api.wealth.intent import extract_quantity

        if self._is_statement_query(user_request) and (
            self._is_transfer_history_only(user_request)
            or not re.search(
                r"分析|统计|合计|总共|一共|报告|环比|最多|最大|异常|可疑|为什么", user_request
            )
        ):
            return RouteDecision(
                route=RequestRoute.ACCOUNT_QUERY,
                requested_output=RequestedOutput.ANSWER,
                confidence=1,
            )

        complete_buy = (
            bool(re.search(r"申购|购买|买入|买", user_request))
            and bool(re.search(r"(?:用|从).+(?:卡|账户)", user_request))
            and bool(
                re.search(
                    r"稳享日日|稳享周周|稳健优选|均衡优选|均衡周享|进取成长|进取周享|高波动精选|第[一二1234]款",
                    user_request,
                )
            )
            and extract_quantity(user_request, "PURCHASE").quantity is not None
        )
        if (
            complete_buy
            and not has_conditional_control(user_request)
            and not re.search(r"适合|如果|费用|自动|定投|调仓|各买|分别买|转账", user_request)
            and get_settings().app_environment in {"development", "test"}
            and get_settings().mock_wealth_enabled
        ):
            return RouteDecision(
                route=RequestRoute.WEALTH_PURCHASE,
                requested_output=RequestedOutput.WORKFLOW,
                confidence=1,
            )
        if get_settings().app_environment in {"development", "test"} and (
            (wealth_context and FOLLOW_UP.search(user_request))
            or EDUCATION.search(user_request)
            or ASSESSMENT_UPDATE.search(user_request)
        ):
            if not has_conditional_control(user_request) and not re.search(
                r"自动|定投|调仓|转账|取消订阅|申购|赎回.*(?:份|全部)", user_request
            ):
                return RouteDecision(
                    route=RequestRoute.WEALTH_ANALYSIS,
                    requested_output=RequestedOutput.ANSWER,
                    confidence=1,
                )
        normalized = "".join(user_request.casefold().split())
        wealth = any(
            word in normalized
            for word in ("理财", "申购", "赎回", "演示稳", "演示均衡", "演示进取", "演示高波动")
        )
        from banking_api.config.settings import get_settings

        read_only_wealth = any(
            word in normalized
            for word in (
                "查询",
                "查看",
                "持仓",
                "订单",
                "资料",
                "说明",
                "比较",
                "对比",
                "推荐",
                "费用",
                "规则",
            )
        )
        if (
            wealth
            and get_settings().app_environment in {"development", "test"}
            and (get_settings().mock_wealth_enabled or read_only_wealth)
        ):
            query_only = any(
                w in normalized
                for w in (
                    "推荐",
                    "适合",
                    "是否",
                    "能买",
                    "对比",
                    "比较",
                    "费用",
                    "手续费",
                    "费率",
                    "起购",
                    "条款",
                    "规则",
                    "多久",
                    "几天",
                    "何时",
                    "说明书",
                    "风险",
                    "开放日",
                    "如何",
                    "怎么",
                    "查询",
                    "到账规则",
                    "申购规则",
                    "赎回规则",
                )
            )
            buys = len(re.findall(r"申购|购买|买入|买", normalized))
            sells = len(re.findall(r"赎回|卖出", normalized))
            writes = (buys + sells) > 0 and not query_only
            unsupported = has_conditional_control(user_request) or any(
                w in normalized
                for w in (
                    "定投",
                    "自动买",
                    "自动投",
                    "调仓",
                    "分批",
                    "分别买",
                    "多笔",
                    "各买",
                    "转账",
                    "取消订阅",
                )
            )
            if writes:
                unsupported = unsupported or bool(
                    re.search(r"(?:余额|消费|支出|净值|收益|资金).{0,20}[<>≤≥]", normalized)
                )
                unsupported = unsupported or bool(
                    re.search(
                        r"只要|就|达到|超过|低于|不少于|不低于|满足|条件|先.*(?:再|然后)|在.+时|后.*(?:买|申购|赎回)",
                        normalized,
                    )
                )
                unsupported = (
                    unsupported
                    or buys + sells > 1
                    or any(w in normalized for w in ("每月", "每周", "定期"))
                )
                # Ambiguous quantities in one intent go to a bounded clarification draft.
                # Multiple writes/products and conditional trading remain unsupported.
                unsupported = (
                    unsupported
                    or len(
                        re.findall(
                            r"(?:演示)?(?:稳享日日|稳享周周|稳健优选|均衡优选|均衡周享|进取成长|进取周享|高波动精选)",
                            normalized,
                        )
                    )
                    > 1
                )
            # General purchase interest opens product discovery, not an empty transaction.
            product_named = bool(
                re.search(
                    r"稳享日日|稳享周周|稳健优选|均衡优选|均衡周享|进取成长|进取周享|高波动精选",
                    normalized,
                )
            )
            purchase_payload = (
                product_named
                and bool(re.search(r"\d", normalized))
                and bool(re.search(r"从.+(?:卡|账户)", normalized))
            )
            route = (
                RequestRoute.UNSUPPORTED
                if unsupported
                else RequestRoute.WEALTH_ANALYSIS
                if not writes or (buys and not sells and not purchase_payload)
                else RequestRoute.WEALTH_REDEEM
                if sells
                else RequestRoute.WEALTH_PURCHASE
            )
            return RouteDecision(
                route=route,
                requested_output=RequestedOutput.WORKFLOW
                if route in {RequestRoute.WEALTH_PURCHASE, RequestRoute.WEALTH_REDEEM}
                else RequestedOutput.ANSWER,
                confidence=1,
            )
        if re.fullmatch(
            r"(?:请问|请|帮我查一下|查一下|查询)?我?(?:可以|能|可)?(?:向|给)"
            r"(?:谁|哪些人|哪些收款人|哪几个收款人)(?:转账|汇款|打款)(?:吗|呢)?[？?。！!]*",
            normalized,
        ):
            return RouteDecision(
                route=RequestRoute.ACCOUNT_QUERY,
                requested_output=RequestedOutput.ANSWER,
                confidence=1.0,
            )
        if (
            re.search(r"每(?:个)?月\d{1,2}(?:号|日)", normalized)
            and any(word in normalized for word in ("转账", "转帐", "汇款", "打款"))
            and not has_conditional_control(user_request)
            and not self._is_multi_capability_intent(user_request)
        ):
            return RouteDecision(
                route=RequestRoute.TRANSFER_WORKFLOW,
                requested_output=RequestedOutput.WORKFLOW,
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
                if decision.route in {
                    RequestRoute.WEALTH_ANALYSIS,
                    RequestRoute.WEALTH_PURCHASE,
                    RequestRoute.WEALTH_REDEEM,
                } and (
                    get_settings().app_environment not in {"development", "test"}
                    or (
                        not get_settings().mock_wealth_enabled
                        and decision.route
                        in {RequestRoute.WEALTH_PURCHASE, RequestRoute.WEALTH_REDEEM}
                    )
                ):
                    return RouteDecision(
                        route=RequestRoute.UNSUPPORTED,
                        requested_output=RequestedOutput.ANSWER,
                        confidence=decision.confidence,
                    )

                normalized = "".join(user_request.casefold().split())
                if has_conditional_control(user_request):
                    return RouteDecision(
                        route=RequestRoute.COMPLEX_PLAN,
                        requested_output=RequestedOutput.ANSWER,
                        confidence=decision.confidence,
                    )
                if self._is_personal_combination(user_request):
                    return RouteDecision(
                        route=RequestRoute.PERSONAL_BANKING,
                        requested_output=decision.requested_output,
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
                if decision.route is RequestRoute.PERSONAL_BANKING:
                    # A model label alone must not grant both read profiles.
                    return RouteDecision(
                        route=RequestRoute.FINANCIAL_ANALYSIS
                        if re.search(r"消费|账单|支出|报告|异常|花费", user_request)
                        else RequestRoute.ACCOUNT_QUERY,
                        requested_output=decision.requested_output,
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
        if RequestRouter._is_statement_query(user_request):
            has_transfer = False
        has_analysis = any(
            marker in normalized
            for marker in ("消费", "报告", "环比", "为什么花", "支出", "异常交易", "账单")
        )
        has_account = any(marker in normalized for marker in ("查余额", "余额", "有哪些账户"))
        has_account = has_account or bool(re.search(r"转账记录|转账历史|流水|账单明细", normalized))
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
            sum(
                (
                    has_transfer,
                    has_analysis or has_account,
                    has_sub_analysis,
                    has_cancel,
                    has_resume,
                )
            )
            >= 2
        )

    @staticmethod
    def _is_personal_combination(user_request: str) -> bool:
        text = "".join(user_request.split())
        account = bool(re.search(r"余额|还剩(?:多少|多少钱)|有哪些账户|账户列表|收款人", text))
        history = RequestRouter._is_statement_query(user_request)
        account = account or history
        spending = (
            bool(re.search(r"消费|支出|账单|报告|花(?:了|费|在)|异常交易", text))
            if not history
            else bool(
                re.search(r"分析|统计|合计|总共|一共|报告|环比|最多|最大|异常|可疑|为什么", text)
            )
        )
        if history and RequestRouter._is_transfer_history_only(text):
            spending = False
        other = bool(
            re.search(r"转账|汇款|打款|转给|取消|恢复|订阅|理财|申购|赎回|买入|定投", text)
        )
        return (
            account
            and spending
            and (history or not other)
            and not has_conditional_control(user_request)
        )

    @staticmethod
    def _is_statement_query(user_request: str) -> bool:
        """Recognize explicit history requests, leaving mixed mutations to the planner."""
        text = "".join(user_request.split())
        if has_conditional_control(text):
            return False
        if re.search(
            r"(?:^|[，。；,;]|然后|再|并|同时)(?:请|帮我|顺便)?(?:给.+转\d|向.+(?:转账|汇款)|(?:转账|汇款|打款).*\d|从.+转|用.+(?:买|申购|赎回)|取消|恢复|预约)",
            text,
        ):
            return False
        if re.search(
            r"(?:再|然后|接着|并且|同时|顺便|并).{0,12}(?:给.+转|转账|汇款|打款|购买|申购|赎回|取消|恢复|预约)|(?:现在|立即|帮我|请)(?:给.+转|转账|汇款|打款|购买|申购|赎回|取消|恢复|预约)|发起|办理|转一笔|每月\d+",
            text,
        ):
            return False
        history = bool(
            re.search(
                r"账单明细|交易明细|收支明细|流水|转账记录|转账历史|汇款记录|扣费记录|扣款记录|购物明细|消费明细|收入明细|支出明细",
                text,
            )
        )
        recent = bool(
            re.search(
                r"(?:最近|近期|近\d+天|上月|本月|今年|去年|\d{4}年).*(?:有哪些转账|转过|转了|收到.*转账|转入|转出|扣了哪些|哪些扣款)",
                text,
            )
        )
        transfer_statistics = bool(
            re.search(
                r"(?:转账|转出|转入|汇款).*(?:总额|合计|一共|总共|汇总|分别|分析|统计)"
                r"|(?:分析|统计|汇总|查看|查询).*(?:转账|转出|转入|汇款)"
                r"|(?:给|向).{1,24}(?:转了|转过|汇过).*(?:多少|记录)",
                text,
            )
        )
        return history or recent or transfer_statistics

    @staticmethod
    def _is_transfer_history_only(text: str) -> bool:
        return (
            RequestRouter._is_statement_query(text)
            and bool(re.search(r"转账|转出|转入|汇款|转了|转过", text))
            and not re.search(r"消费|购物|花费|开销|异常|可疑|订阅|理财|申购|赎回|报告", text)
        )
