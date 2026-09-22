"""Opt-in real-provider routing and specialist-agent smoke test."""

import asyncio
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from banking_api.agents.financial_analysis_agent import FINANCIAL_ANALYSIS_AGENT
from banking_api.agents.minimal_banking_agent import MINIMAL_BANKING_AGENT
from banking_api.config.settings import Settings
from banking_api.context.builder import ContextBuilder
from banking_api.domain.enums import MessageRole
from banking_api.domain.message import Message
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.llm.openai_compatible_provider import OpenAICompatibleProvider
from banking_api.mock_bank.service import MockBankService
from banking_api.policy.service import PolicyService
from banking_api.registries.agent_registry import AgentRegistry
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.routing.models import RequestRoute
from banking_api.routing.request_router import RequestRouter
from banking_api.runtime.base import AgentRunRequest, SuccessfulToolResult
from banking_api.runtime.langgraph.checkpoint import LangGraphCheckpointManager
from banking_api.runtime.langgraph.graph import LangGraphAgentRuntime
from banking_api.tools.banking import (
    build_compare_spending_periods_tool,
    build_get_balance_tool,
    build_get_category_breakdown_tool,
    build_get_spending_summary_tool,
    build_get_top_transactions_tool,
    build_list_accounts_tool,
)
from banking_api.tools.executor import ToolExecutor

ROUTE_AGENT = {
    RequestRoute.MINIMAL_BANKING: MINIMAL_BANKING_AGENT.agent_id,
    RequestRoute.FINANCIAL_ANALYSIS: FINANCIAL_ANALYSIS_AGENT.agent_id,
}


def evidence_summary(result: SuccessfulToolResult) -> dict[str, Any]:
    output = result.output
    summary: dict[str, Any] = {
        "capability_id": result.capability_id,
        "input": result.arguments,
    }
    if result.capability_id == "account.list":
        summary["account_ids"] = [item["account_id"] for item in output["accounts"]]
    elif result.capability_id == "transaction.spending_summary":
        summary["result"] = {
            key: output[key]
            for key in (
                "period",
                "total_income",
                "total_spending",
                "income_transaction_count",
                "spending_transaction_count",
                "currency",
            )
        }
    elif result.capability_id == "transaction.category_breakdown":
        summary["result"] = {
            "period": output["period"],
            "total_spending": output["total_spending"],
            "categories": [
                {"category": item["category"], "amount": item["amount"]}
                for item in output["categories"]
            ],
        }
    elif result.capability_id == "transaction.compare_periods":
        summary["result"] = {
            key: output[key]
            for key in (
                "current_period",
                "previous_period",
                "current_spending",
                "previous_spending",
                "absolute_change",
                "percentage_change",
                "currency",
            )
        }
    elif result.capability_id == "transaction.top_transactions":
        summary["result"] = {
            "period": output["period"],
            "item_count": len(output["transactions"]),
            "transaction_ids": [
                item["transaction_id"] for item in output["transactions"]
            ],
        }
    return summary


async def main() -> None:
    settings = Settings()
    if not settings.llm_base_url or not settings.llm_api_key or not settings.llm_model:
        raise SystemExit("LLM_BASE_URL, LLM_API_KEY and LLM_MODEL are required")
    print(
        "provider.config",
        {
            "provider": settings.llm_provider,
            "base_url_domain": urlparse(settings.llm_base_url).netloc,
            "model": settings.llm_model,
        },
    )
    provider = OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    bank = MockBankService()
    analytics = FinancialAnalyticsService(bank)
    tools = ToolRegistry()
    tools.register(build_list_accounts_tool(bank))
    tools.register(build_get_balance_tool(bank))
    tools.register(build_get_spending_summary_tool(analytics))
    tools.register(build_get_category_breakdown_tool(analytics))
    tools.register(build_compare_spending_periods_tool(analytics))
    tools.register(build_get_top_transactions_tool(analytics))
    agents = AgentRegistry()
    agents.register(MINIMAL_BANKING_AGENT)
    agents.register(FINANCIAL_ANALYSIS_AGENT)
    router = RequestRouter(provider)
    checkpoint_manager = LangGraphCheckpointManager(
        settings.langgraph_checkpoint_database_url or settings.database_url,
        strict_msgpack=settings.langgraph_strict_msgpack,
    )
    runtime = LangGraphAgentRuntime(
        provider=provider,
        registry=tools,
        executor=ToolExecutor(tools, PolicyService()),
        context_builder=ContextBuilder(),
        checkpointer=await checkpoint_manager.start(),
        max_steps=settings.agent_max_steps,
        max_tool_calls=settings.agent_max_tool_calls,
    )
    try:
        for prompt in (
            "我有哪些账户？",
            "帮我分析一下2026年8月份消费",
            "分析一下工资卡2026年8月的消费",
        ):
            decision = await router.route(prompt)
            agent_id = ROUTE_AGENT.get(decision.route)
            print(
                "request.routed",
                {"route": decision.route.value, "executor_id": agent_id},
            )
            if agent_id is None:
                print("final.answer", "当前不支持该请求。")
                continue
            agent = agents.get(agent_id)
            if agent is None:
                raise RuntimeError("Routed agent is not registered")
            conversation_id = uuid4()
            message = Message(
                message_id=uuid4(),
                conversation_id=conversation_id,
                role=MessageRole.USER,
                content=prompt,
                created_at=datetime.now(UTC),
            )
            result = await runtime.run(
                AgentRunRequest(
                    task_id=uuid4(),
                    conversation_id=conversation_id,
                    current_task=prompt,
                    conversation_messages=[message],
                    authenticated=True,
                    agent=agent,
                )
            )
            print("agent.selected", agent.agent_id)
            for evidence in result.state.successful_tool_results:
                print("tool.evidence", evidence_summary(evidence))
            print("final.answer", result.answer)
    finally:
        await checkpoint_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
