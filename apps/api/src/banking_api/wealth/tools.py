from datetime import datetime
from uuid import UUID

from pydantic import Field

from banking_api.domain.enums import RiskLevel
from banking_api.knowledge.wealth import KeywordWealthKnowledge
from banking_api.tools.models import ToolSpec
from banking_api.wealth.schemas import (
    CompareInput,
    RecommendationInput,
    WealthAnalysisInput,
    WealthInput,
    WealthReadResult,
)
from banking_api.wealth.service import WealthService

CALLER = "agent:wealth-advisor"
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


class ProviderOutput(WealthInput):
    outcome: str | None = None
    status: str | None = None
    provider_reference: str | None = None
    error_code: str | None = None
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
            description=f"模拟理财只读：{name}。数字及排序以工具结果为准。",
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
            output = await (provider.query if query else provider.submit)(
                args.operation_id, context.principal.user_id, direction
            )
            return ProviderOutput(**output)

        return ToolSpec(
            capability_id=f"wealth.{direction.lower()}.{'status' if query else 'submit'}",
            name=name,
            description="只处理已持久化且授权的理财 Operation",
            input_model=OperationInput,
            output_model=ProviderOutput,
            risk_level=RiskLevel.R1_PRIVATE_READ if query else RiskLevel.R4_FINANCIAL_COMMIT,
            side_effect=not query,
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
