from banking_api.agents.financial_analysis_agent import FINANCIAL_ANALYSIS_AGENT
from banking_api.api.dependencies import get_current_principal
from banking_api.domain.principal import ExecutionPrincipal, Principal
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.mock_bank.service import MockBankService
from banking_api.policy.service import PolicyService
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.tools.banking import (
    build_get_balance_tool,
    build_get_spending_summary_tool,
    build_list_accounts_tool,
    build_search_payees_tool,
)
from banking_api.tools.executor import ToolExecutor
from banking_api.tools.models import ToolErrorCode


async def test_conversation_task_event_and_sse_cross_user_isolation(app, client) -> None:
    conversation = await client.post("/api/v1/conversations", json={"title": "Owned by A"})
    conversation_id = conversation.json()["conversation_id"]
    accepted = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "Hello"},
    )
    task_id = accepted.json()["task_id"]

    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="user-b", issuer="test", subject="user-b"
    )
    try:
        assert (await client.get(f"/api/v1/conversations/{conversation_id}")).status_code == 404
        assert (await client.get(f"/api/v1/tasks/{task_id}")).status_code == 404
        assert (await client.get(f"/api/v1/tasks/{task_id}/events")).status_code == 404
        assert (
            await client.get(
                f"/api/v1/events?conversation_id={conversation_id}",
                timeout=1,
            )
        ).status_code == 404
        assert (await client.get("/api/v1/conversations")).json() == []
        assert (await client.get("/api/v1/tasks")).json() == []
    finally:
        app.dependency_overrides.pop(get_current_principal)


async def test_banking_tools_cannot_switch_authority_via_arguments() -> None:
    bank = MockBankService()
    bank._accounts.append(  # type: ignore[attr-defined]
        {
            "user_id": "user-b",
            "account_id": "account-b",
            "display_name": "B only",
            "account_type": "DEBIT",
            "masked_number": "****9999",
            "currency": "CNY",
            "status": "ACTIVE",
            "balance": "999999.00",
        }
    )
    bank._payees.append(  # type: ignore[attr-defined]
        {
            "user_id": "user-b",
            "payee_id": "payee-b",
            "display_name": "B Payee",
            "bank_name": "Test",
            "masked_account": "****9999",
            "phone_alias": "13900000000",
        }
    )
    registry = ToolRegistry()
    registry.register(build_list_accounts_tool(bank))
    registry.register(build_get_balance_tool(bank))
    registry.register(build_search_payees_tool(bank))
    registry.register(build_get_spending_summary_tool(FinancialAnalyticsService(bank)))
    executor = ToolExecutor(registry, PolicyService())
    principal = ExecutionPrincipal.for_task("dev-user-001")

    accounts = await executor.execute(
        tool_name="list_accounts",
        arguments={},
        caller="agent:minimal-banking",
        principal=principal,
        agent_allowlist=frozenset({"account.list", "account.get_balance"}),
    )
    assert accounts.ok
    assert "account-b" not in {item["account_id"] for item in (accounts.output or {})["accounts"]}

    injected = await executor.execute(
        tool_name="list_accounts",
        arguments={"user_id": "user-b"},
        caller="agent:minimal-banking",
        principal=principal,
        agent_allowlist=frozenset({"account.list", "account.get_balance"}),
    )
    assert injected.error is not None
    assert injected.error.code is ToolErrorCode.TOOL_ARGUMENT_VALIDATION_FAILED

    foreign_balance = await executor.execute(
        tool_name="get_balance",
        arguments={"account_id": "account-b"},
        caller="agent:minimal-banking",
        principal=principal,
        agent_allowlist=frozenset({"account.list", "account.get_balance"}),
    )
    assert foreign_balance.ok is False

    foreign_payee = await executor.execute(
        tool_name="search_payees",
        arguments={"query": "B Payee"},
        caller="workflow:transfer",
        principal=principal,
        agent_allowlist=frozenset({"payee.search"}),
    )
    assert foreign_payee.output == {"payees": []}

    foreign_analysis = await executor.execute(
        tool_name="get_spending_summary",
        arguments={"month": "2026-08", "account_ids": ["account-b"]},
        caller="agent:financial-analysis",
        principal=principal,
        agent_allowlist=FINANCIAL_ANALYSIS_AGENT.allowed_capabilities,
    )
    assert foreign_analysis.ok is False
