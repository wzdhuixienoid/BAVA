from datetime import datetime
from uuid import UUID

from pydantic import Field

from banking_api.domain.enums import RiskLevel
from banking_api.domain.operation import OperationProviderResult, OperationType
from banking_api.knowledge.wealth import KeywordWealthKnowledge
from banking_api.tools.models import ToolSpec
from banking_api.tools.operation_authority import authorized_operation
from banking_api.wealth.schemas import (
    CompareInput,
    RecommendationInput,
    WealthAnalysisInput,
    WealthInput,
    WealthReadResult,
)
from banking_api.wealth.service import WealthService

CALLER = "agent:wealth-advisor"
READ_DESCRIPTIONS = {
    "list_products": "列出当前可查询的模拟理财产品及本人购买资格；不创建交易。",
    "get_product": "按 product_id 查询模拟理财产品的版本化条款、风险、费用和本人购买资格。",
    "compare_products": (
        "按 product_ids 比较最多四款模拟产品的风险、费用和到账安排；"
        "可传本次需求、金额和本人账户。"
    ),
    "recommend": (
        "按本次需求、金额、本人账户和有效测评生成有依据的模拟理财候选；"
        "缺失条件返回澄清，不下单。"
    ),
    "search_knowledge": (
        "按 query 检索有效理财资料；可限定产品或版本，"
        "order_id 仅允许本人订单绑定的历史版本。"
    ),
    "list_positions": "查询本人已确认的模拟理财持仓、份额和可赎回情况；不把待成交订单当作持仓。",
    "get_orders": "查询本人模拟理财申请与订单的当前状态；纯读取，不推进成交或到账。",
}
READS = frozenset(
    f"wealth.{name}"
    for name in (
        "list_products",
        "get_product",
        "compare_products",
        "recommend",
        "search_knowledge",
        "list_positions",
        "get_orders",
    )
)


class ProductInput(WealthInput):
    product_id: str = Field(min_length=1, max_length=40)


class KnowledgeInput(WealthInput):
    product_id: str | None = Field(default=None, max_length=40)
    query: str = Field(min_length=1, max_length=300)
    version_id: str | None = Field(default=None, max_length=80)
    order_id: UUID | None = None


class OperationInput(WealthInput):
    operation_id: UUID


class ProviderOutput(OperationProviderResult):
    next_reconcile_at: datetime | None = None


def build_wealth_tools(factory, balances, provider):
    specs = []

    def read_spec(name, input_model):
        async def read_handler(context, args):
            async with factory() as session:
                service = WealthService(session, balances, provider.clock)
                user_id = context.principal.user_id
                if name == "list_products":
                    return WealthReadResult(products=await service.products(user_id))
                if name == "get_product":
                    return WealthReadResult(
                        products=[await service.product(args.product_id, user_id)]
                    )
                if name == "compare_products":
                    from banking_api.wealth.advisory import WealthAdvisoryService

                    return WealthReadResult(
                        products=await service.compare(args.product_ids, user_id),
                        analysis=await WealthAdvisoryService(service).analyze(
                            user_id,
                            WealthAnalysisInput(intent="COMPARISON", **args.model_dump()),
                        ),
                    )
                if name == "recommend":
                    from banking_api.wealth.advisory import WealthAdvisoryService

                    result = await WealthAdvisoryService(service).recommendation(user_id, args)
                    return WealthReadResult(**result.model_dump())
                if name == "list_positions":
                    return WealthReadResult(positions=await service.positions(user_id))
                if name == "get_orders":
                    return WealthReadResult(orders=await service.orders(user_id))
                version = args.version_id
                if args.order_id:
                    from banking_api.wealth.models import WealthOrder

                    order = await session.get(WealthOrder, args.order_id)
                    if (
                        not order
                        or order.user_id != user_id
                        or (args.product_id and order.product_id != args.product_id)
                    ):
                        return WealthReadResult(reasons=["未找到本人订单"])
                    if version and version != order.version_id:
                        return WealthReadResult(reasons=["指定版本与本人订单绑定资料不一致"])
                    args.product_id, version = order.product_id, order.version_id
                evidence = await KeywordWealthKnowledge(service).search(
                    args.product_id, args.query, version
                )
                return WealthReadResult(
                    evidence=evidence,
                    evidence_sources=await KeywordWealthKnowledge(service).fragments(
                        args.query, product_id=args.product_id, version_id=version
                    ),
                    reasons=[] if evidence else ["没有找到相关有效资料，不能补造条款"],
                )

        async def handler(context, args):
            from banking_api.mock_bank.service import AccountNotFoundError
            from banking_api.wealth.calculation import WealthError

            try:
                result = await read_handler(context, args)
                result.result_kind = {
                    "list_products": "CATALOGUE",
                    "get_product": "PRODUCT",
                    "compare_products": "COMPARISON",
                    "recommend": "RECOMMENDATION",
                    "search_knowledge": "KNOWLEDGE",
                    "list_positions": "POSITIONS",
                    "get_orders": "ORDERS",
                }[name]
                return result
            except WealthError as exc:
                return WealthReadResult(reasons=[str(exc)])
            except AccountNotFoundError:
                return WealthReadResult(reasons=["未找到本人账户"])

        return ToolSpec(
            capability_id=f"wealth.{name}",
            name=f"wealth_{name}",
            description=READ_DESCRIPTIONS[name] + "数字及排序以工具结果为准。",
            input_model=input_model,
            output_model=WealthReadResult,
            risk_level=RiskLevel.R1_PRIVATE_READ,
            side_effect=False,
            allowed_callers=frozenset({CALLER}),
            handler=handler,
        )

    for name, model in (
        ("list_products", WealthInput),
        ("get_product", ProductInput),
        ("compare_products", CompareInput),
        ("recommend", RecommendationInput),
        ("search_knowledge", KnowledgeInput),
        ("list_positions", WealthInput),
        ("get_orders", WealthInput),
    ):
        specs.append(read_spec(name, model))

    def operation_spec(direction, query):
        caller = f"workflow:wealth-{direction.lower()}"
        name = f"wealth_{direction.lower()}_{'status' if query else 'submit'}"

        async def handler(context, args):
            async with factory() as session:
                operation = await authorized_operation(
                    session,
                    args.operation_id,
                    context.principal.user_id,
                    (OperationType("WEALTH_" + direction),),
                )
            if operation is None:
                return ProviderOutput(
                    **{
                        "status" if query else "outcome": "UNKNOWN" if query else "FAILED",
                        "error_code": "OPERATION_NOT_FOUND",
                    }
                )
            output = await (provider.query if query else provider.submit)(
                args.operation_id, context.principal.user_id, direction
            )
            return ProviderOutput(**output)

        return ToolSpec(
            capability_id=f"wealth.{direction.lower()}.{'status' if query else 'submit'}",
            name=name,
            description="对账并推进已受理理财订单的成交与到账"
            if query
            else "提交已持久化且授权的理财 Operation",
            input_model=OperationInput,
            output_model=ProviderOutput,
            risk_level=RiskLevel.R3_FINANCIAL_RECONCILE if query else RiskLevel.R4_FINANCIAL_COMMIT,
            side_effect=True,
            allowed_callers=frozenset({caller}),
            handler=handler,
        )

    for direction in ("PURCHASE", "REDEEM"):
        for query in (False, True):
            specs.append(operation_spec(direction, query))
    return specs


class WealthExecutionEngine:
    def __init__(self, executor, balances):
        self.executor, self.balances = executor, balances

    async def execute(self, operation, principal, query):
        direction = operation.operation_type.value.removeprefix("WEALTH_").lower()
        cap = f"wealth.{direction}.{'status' if query else 'submit'}"
        result = await self.executor.execute(
            tool_name=f"wealth_{direction}_{'status' if query else 'submit'}",
            arguments={"operation_id": str(operation.operation_id)},
            caller=f"workflow:wealth-{direction}",
            principal=principal,
            agent_allowlist=frozenset({cap}),
        )
        if not result.ok or not result.output:
            return {
                "status" if query else "outcome": "UNKNOWN",
                "error_code": "PROVIDER_UNAVAILABLE",
            }
        return result.output
