from banking_api.domain.enums import RiskLevel
from banking_api.policy.service import PolicyService
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.tools.executor import ToolExecutor
from banking_api.tools.models import (
    BalanceResult,
    ListAccountsInput,
    ToolErrorCode,
    ToolSpec,
)


async def test_tool_output_validation_failure_is_structured() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            capability_id="test.bad_output",
            name="bad_output",
            description="test only",
            input_model=ListAccountsInput,
            output_model=BalanceResult,
            risk_level=RiskLevel.R1_PRIVATE_READ,
            side_effect=False,
            allowed_callers=frozenset({"agent:test"}),
            handler=lambda _: {"unexpected": True},
        )
    )

    result = await ToolExecutor(registry, PolicyService()).execute(
        tool_name="bad_output",
        arguments={},
        caller="agent:test",
        authenticated=True,
        agent_allowlist=frozenset({"test.bad_output"}),
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.TOOL_OUTPUT_VALIDATION_FAILED


async def test_unauthenticated_tool_call_is_denied() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            capability_id="test.read",
            name="test_read",
            description="test only",
            input_model=ListAccountsInput,
            output_model=BalanceResult,
            risk_level=RiskLevel.R1_PRIVATE_READ,
            side_effect=False,
            allowed_callers=frozenset({"agent:test"}),
            handler=lambda _: {},
        )
    )

    result = await ToolExecutor(registry, PolicyService()).execute(
        tool_name="test_read",
        arguments={},
        caller="agent:test",
        authenticated=False,
        agent_allowlist=frozenset({"test.read"}),
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.TOOL_NOT_ALLOWED
