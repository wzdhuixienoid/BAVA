"""Opt-in real-provider smoke for the read-only transfer draft workflow."""

import asyncio
from urllib.parse import urlparse

from banking_api.config.settings import Settings
from banking_api.llm.openai_compatible_provider import OpenAICompatibleProvider
from banking_api.mock_bank.service import MockBankService
from banking_api.policy.service import PolicyService
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.routing.models import RequestRoute
from banking_api.routing.request_router import RequestRouter
from banking_api.tools.banking import (
    build_get_balance_tool,
    build_list_accounts_tool,
    build_search_payees_tool,
)
from banking_api.tools.executor import ToolExecutor
from banking_api.workflows.transfer.engine import TransferWorkflowEngine
from banking_api.workflows.transfer.intent_extractor import TransferIntentExtractor


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
    prompt = "给张三转2000"
    decision = await RequestRouter(provider).route(prompt)
    if decision.route is not RequestRoute.TRANSFER_WORKFLOW:
        raise AssertionError(f"unexpected route: {decision.route.value}")
    intent = await TransferIntentExtractor(provider).extract(prompt)
    if intent.recipient_query != "张三" or intent.amount is None:
        raise AssertionError("intent extraction did not preserve recipient and amount")

    bank = MockBankService()
    balances_before = {
        item["account_id"]: bank.get_balance(item["account_id"])["balance"]
        for item in bank.list_accounts()
    }
    transactions_before = bank.list_transactions()
    registry = ToolRegistry()
    registry.register(build_list_accounts_tool(bank))
    registry.register(build_get_balance_tool(bank))
    registry.register(build_search_payees_tool(bank))
    engine = TransferWorkflowEngine(ToolExecutor(registry, PolicyService()))

    status, state = await engine.start(intent)
    if status.value != "WAITING_FOR_INPUT" or state.required_input is None:
        raise AssertionError("expected payee selection")
    if len(state.required_input.options) != 2:
        raise AssertionError("expected exactly two deterministic 张三 candidates")
    await engine.validate_payee_action(state, "payee_001")
    state.draft.payee_id = "payee_001"
    status, state = await engine.advance(state)
    if status.value != "WAITING_FOR_INPUT":
        raise AssertionError("expected source account selection")
    await engine.validate_account_action(state, "acc_salary")
    state.draft.source_account_id = "acc_salary"
    status, state = await engine.advance(state)
    if status.value != "READY_FOR_REVIEW":
        raise AssertionError(f"unexpected final status: {status.value}")

    balances_after = {
        item["account_id"]: bank.get_balance(item["account_id"])["balance"]
        for item in bank.list_accounts()
    }
    if balances_before != balances_after or transactions_before != bank.list_transactions():
        raise AssertionError("read-only transfer draft mutated bank data")
    capabilities = {spec.capability_id for spec in registry.all()}
    if capabilities != {"account.list", "account.get_balance", "payee.search"}:
        raise AssertionError("unexpected capability registered")
    print(
        "smoke.result",
        {
            "route": decision.route.value,
            "recipient": intent.recipient_query,
            "payee_candidates": 2,
            "source_account": "acc_salary",
            "status": status.value,
            "write_calls": 0,
            "balance_unchanged": True,
            "transactions_unchanged": True,
        },
    )


if __name__ == "__main__":
    asyncio.run(main())
