import pytest

from banking_api.agents.financial_analysis_agent import FINANCIAL_ANALYSIS_AGENT
from banking_api.agents.minimal_banking_agent import MINIMAL_BANKING_AGENT
from banking_api.domain.enums import PolicyDecision, RiskLevel
from banking_api.domain.principal import ExecutionPrincipal
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.financial.errors import FinancialErrorCode
from banking_api.main import create_app
from banking_api.mock_bank.service import MockBankService
from banking_api.policy.service import PolicyService
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.tools.banking import (
    build_compare_spending_periods_tool,
    build_get_category_breakdown_tool,
    build_get_spending_summary_tool,
    build_get_top_transactions_tool,
)
from banking_api.tools.banking.get_spending_summary import FINANCIAL_ANALYSIS_AGENT_ID
from banking_api.tools.executor import ToolExecutor
from banking_api.tools.models import ToolErrorCode, ToolSpec

FINANCIAL_CAPABILITIES = frozenset(
    {
        "transaction.spending_summary",
        "transaction.category_breakdown",
        "transaction.compare_periods",
        "transaction.top_transactions",
    }
)
TEST_PRINCIPAL = ExecutionPrincipal.for_task("dev-user-001")


@pytest.fixture
def financial_tools() -> tuple[ToolRegistry, ToolExecutor]:
    analytics = FinancialAnalyticsService(MockBankService())
    registry = ToolRegistry()
    registry.register(build_get_spending_summary_tool(analytics))
    registry.register(build_get_category_breakdown_tool(analytics))
    registry.register(build_compare_spending_periods_tool(analytics))
    registry.register(build_get_top_transactions_tool(analytics))
    return registry, ToolExecutor(registry, PolicyService())


def test_financial_tools_are_r1_read_only_and_financial_agent_only(
    financial_tools: tuple[ToolRegistry, ToolExecutor],
) -> None:
    registry, _ = financial_tools

    assert {spec.capability_id for spec in registry.all()} == FINANCIAL_CAPABILITIES
    assert all(spec.risk_level is RiskLevel.R1_PRIVATE_READ for spec in registry.all())
    assert all(spec.side_effect is False for spec in registry.all())
    assert all(
        spec.allowed_callers == frozenset({FINANCIAL_ANALYSIS_AGENT_ID}) for spec in registry.all()
    )
    assert registry.get_by_name("transaction.search") is None


def test_application_registry_adds_financial_tools_without_expanding_minimal_agent() -> None:
    registry = create_app().state.tool_registry

    assert {spec.capability_id for spec in registry.all()} == {
        "account.list",
        "account.get_balance",
        "payee.search",
        "transfer.commit",
        "transfer.get_status",
        "subscription.analyze",
        "subscription.cancel",
        "subscription.get_status",
        *FINANCIAL_CAPABILITIES,
    }
    assert [
        spec.capability_id for spec in registry.resolve(MINIMAL_BANKING_AGENT.allowed_capabilities)
    ] == ["account.list", "account.get_balance"]
    assert "transfer.commit" not in MINIMAL_BANKING_AGENT.allowed_capabilities
    assert "transfer.get_status" not in MINIMAL_BANKING_AGENT.allowed_capabilities
    assert "transfer.commit" not in FINANCIAL_ANALYSIS_AGENT.allowed_capabilities
    assert "transfer.get_status" not in FINANCIAL_ANALYSIS_AGENT.allowed_capabilities


@pytest.mark.parametrize("capability_id", sorted(FINANCIAL_CAPABILITIES))
def test_policy_allows_financial_agent_for_each_tool(
    capability_id: str,
    financial_tools: tuple[ToolRegistry, ToolExecutor],
) -> None:
    registry, _ = financial_tools
    spec = registry.get(capability_id)
    assert spec is not None

    result = PolicyService().evaluate(
        spec=spec,
        caller=FINANCIAL_ANALYSIS_AGENT_ID,
        authenticated=True,
        agent_allowlist=FINANCIAL_CAPABILITIES,
    )
    assert result.decision is PolicyDecision.ALLOW


@pytest.mark.parametrize("capability_id", sorted(FINANCIAL_CAPABILITIES))
def test_policy_denies_minimal_agent_for_each_transaction_tool(
    capability_id: str,
    financial_tools: tuple[ToolRegistry, ToolExecutor],
) -> None:
    registry, _ = financial_tools
    spec = registry.get(capability_id)
    assert spec is not None

    result = PolicyService().evaluate(
        spec=spec,
        caller="agent:minimal-banking",
        authenticated=True,
        agent_allowlist=frozenset({"account.list", "account.get_balance"}),
    )
    assert result.decision is PolicyDecision.DENY


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_key"),
    [
        ("get_spending_summary", {"month": "2026-08"}, "total_spending"),
        ("get_category_breakdown", {"month": "2026-08"}, "categories"),
        ("compare_spending_periods", {"month": "2026-08"}, "category_changes"),
        ("get_top_transactions", {"month": "2026-08", "limit": 3}, "transactions"),
    ],
)
async def test_financial_tools_execute_through_registry_policy_and_executor(
    tool_name: str,
    arguments: dict[str, object],
    expected_key: str,
    financial_tools: tuple[ToolRegistry, ToolExecutor],
) -> None:
    _, executor = financial_tools

    result = await executor.execute(
        tool_name=tool_name,
        arguments=arguments,
        caller=FINANCIAL_ANALYSIS_AGENT_ID,
        principal=TEST_PRINCIPAL,
        agent_allowlist=FINANCIAL_CAPABILITIES,
    )
    assert result.ok is True
    assert result.output is not None
    assert expected_key in result.output
    if tool_name == "get_top_transactions":
        assert len(result.output["transactions"]) == 3


async def test_minimal_agent_cannot_execute_financial_tool(
    financial_tools: tuple[ToolRegistry, ToolExecutor],
) -> None:
    _, executor = financial_tools

    result = await executor.execute(
        tool_name="get_spending_summary",
        arguments={"month": "2026-08"},
        caller="agent:minimal-banking",
        principal=TEST_PRINCIPAL,
        agent_allowlist=frozenset({"account.list", "account.get_balance"}),
    )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.TOOL_NOT_ALLOWED


@pytest.mark.parametrize(
    ("arguments", "expected_code"),
    [
        ({"month": "2026-8"}, FinancialErrorCode.INVALID_PERIOD),
        (
            {"month": "2026-08", "account_ids": ["missing"]},
            FinancialErrorCode.ACCOUNT_NOT_FOUND,
        ),
        ({"month": "2025-01"}, FinancialErrorCode.NO_TRANSACTIONS_IN_PERIOD),
    ],
)
async def test_financial_domain_errors_remain_structured(
    arguments: dict[str, object],
    expected_code: FinancialErrorCode,
    financial_tools: tuple[ToolRegistry, ToolExecutor],
) -> None:
    _, executor = financial_tools

    result = await executor.execute(
        tool_name="get_spending_summary",
        arguments=arguments,
        caller=FINANCIAL_ANALYSIS_AGENT_ID,
        principal=TEST_PRINCIPAL,
        agent_allowlist=FINANCIAL_CAPABILITIES,
    )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is expected_code
    assert result.error.retryable is False


@pytest.mark.parametrize("limit", [0, 21])
async def test_top_transaction_limit_is_schema_bounded(
    limit: int,
    financial_tools: tuple[ToolRegistry, ToolExecutor],
) -> None:
    _, executor = financial_tools

    result = await executor.execute(
        tool_name="get_top_transactions",
        arguments={"month": "2026-08", "limit": limit},
        caller=FINANCIAL_ANALYSIS_AGENT_ID,
        principal=TEST_PRINCIPAL,
        agent_allowlist=FINANCIAL_CAPABILITIES,
    )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.TOOL_ARGUMENT_VALIDATION_FAILED


def test_tool_schemas_are_pydantic_and_do_not_expose_raw_month_history(
    financial_tools: tuple[ToolRegistry, ToolExecutor],
) -> None:
    registry, _ = financial_tools
    top_spec = registry.get("transaction.top_transactions")
    assert isinstance(top_spec, ToolSpec)
    assert top_spec.input_schema["properties"]["limit"]["maximum"] == 20
    assert "transactions" in top_spec.output_schema["properties"]
    assert registry.get("transaction.search") is None
