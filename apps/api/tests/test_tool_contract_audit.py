"""Regression checks for function-call contracts, authority and posted financial facts."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel, ValidationError
from test_runtime_parity import build_runtime, request
from test_subscription_notifications import runtime as subscription_runtime
from test_transfer_operations import authorize_workflow, operation_runtime

from banking_api.agents.subscription_analysis_agent import SUBSCRIPTION_ANALYSIS_AGENT
from banking_api.application.account_statement_service import (
    AccountStatementService,
    PostedAnalysisBank,
)
from banking_api.application.operation_service import OperationService
from banking_api.domain.enums import ApprovalStatus, PolicyDecision, RiskLevel
from banking_api.domain.operation import OperationProviderResult, OperationType
from banking_api.domain.principal import ExecutionPrincipal
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.llm.models import LLMMessage, LLMResponse, LLMToolCall
from banking_api.llm.openai_compatible_provider import OpenAICompatibleProvider
from banking_api.main import create_app
from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import ApprovalModel, OperationModel
from banking_api.policy.service import PolicyService
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.tools.banking import build_get_spending_summary_tool, build_list_accounts_tool
from banking_api.tools.executor import ToolExecutor
from banking_api.tools.models import BalanceResult, ToolErrorCode
from banking_api.tools.operation_authority import authorized_operation
from banking_api.wealth.schemas import RecommendationInput


def test_all_registered_tools_have_valid_contract_and_reconcile_classification():
    specs = create_app().state.tool_registry.all()
    assert len(specs) == 27
    reads = [s for s in specs if s.risk_level == RiskLevel.R1_PRIVATE_READ]
    writes = [s for s in specs if s.risk_level == RiskLevel.R4_FINANCIAL_COMMIT]
    reconciles = [s for s in specs if s.risk_level == RiskLevel.R3_FINANCIAL_RECONCILE]
    assert (len(reads), len(writes), len(reconciles)) == (19, 5, 3)
    assert {s.capability_id for s in reconciles} == {
        "transfer.get_status",
        "wealth.purchase.status",
        "wealth.redeem.status",
    }
    policy = PolicyService()
    for spec in specs:
        assert spec.input_schema["additionalProperties"] is False
        assert spec.output_schema["type"] == "object"
        for caller in spec.allowed_callers:
            result = policy.evaluate(
                spec=spec,
                caller=caller,
                authenticated=True,
                agent_allowlist=frozenset({spec.capability_id}),
            )
            assert result.decision == PolicyDecision.ALLOW
        if spec.side_effect:
            assert all(c.startswith("workflow:") for c in spec.allowed_callers)
            for caller in (
                "agent:personal-banking",
                "agent:personal-banking",
                "agent:wealth-advisor",
            ):
                assert (
                    policy.evaluate(
                        spec=spec,
                        caller=caller,
                        authenticated=True,
                        agent_allowlist=frozenset({spec.capability_id}),
                    ).decision
                    == PolicyDecision.DENY
                )


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "invalid.function"},
        {"name": "x" * 65},
        {"allowed_callers": frozenset()},
        {"side_effect": True},
        {"input_model": BaseModel},
        {"risk_level": RiskLevel.R3_FINANCIAL_RECONCILE, "side_effect": True},
    ],
)
def test_registry_revalidates_copied_contracts(changes):
    spec = build_list_accounts_tool(MockBankService()).model_copy(update=changes)
    with pytest.raises((ValueError, TypeError)):
        ToolRegistry().register(spec)


@pytest.mark.parametrize(
    "output",
    [
        {},
        {"outcome": "SUCCEEDED"},
        {"status": "ACCEPTED"},
        {"outcome": "ACCEPTED", "status": "SUCCEEDED"},
    ],
)
def test_provider_result_rejects_empty_ambiguous_and_invalid_states(output):
    with pytest.raises(ValidationError):
        OperationProviderResult.model_validate(output)


async def execute_spec(spec, arguments):
    registry = ToolRegistry()
    registry.register(spec)
    return await ToolExecutor(registry, PolicyService()).execute(
        tool_name=spec.name,
        arguments=arguments,
        caller=next(iter(spec.allowed_callers)),
        principal=ExecutionPrincipal.for_task("dev-user-001"),
        agent_allowlist=frozenset({spec.capability_id}),
    )


async def test_invalid_wealth_quantity_is_recoverable_and_never_calls_handler():
    handler = AsyncMock()
    spec = build_list_accounts_tool(MockBankService()).model_copy(
        update={
            "input_model": RecommendationInput,
            "handler": handler,
        }
    )
    result = await execute_spec(spec, {"amount": "NaN"})
    assert result.error.code == ToolErrorCode.TOOL_ARGUMENT_VALIDATION_FAILED
    assert result.error.retryable
    handler.assert_not_awaited()


async def test_forged_model_output_cannot_bypass_validation():
    forged = BalanceResult.model_construct(
        account_id="x", display_name="x", masked_number="x", currency="CNY", balance="not-money"
    )
    spec = build_list_accounts_tool(MockBankService()).model_copy(
        update={
            "output_model": BalanceResult,
            "handler": lambda *_: forged,
        }
    )
    result = await execute_spec(spec, {})
    assert result.error.code == ToolErrorCode.TOOL_OUTPUT_VALIDATION_FAILED


async def test_forged_input_model_cannot_bypass_argument_validation():
    handler = AsyncMock()
    spec = build_list_accounts_tool(MockBankService()).model_copy(
        update={"input_model": RecommendationInput, "handler": handler}
    )
    result = await execute_spec(spec, RecommendationInput.model_construct(amount="NaN"))
    assert result.error.code == ToolErrorCode.TOOL_ARGUMENT_VALIDATION_FAILED
    handler.assert_not_awaited()


async def test_manual_uses_selected_agent_instead_of_default_agent_permissions():
    runtime, provider = build_runtime("manual", [LLMResponse(content="订阅查询完成")])
    selected = replace(request(), agent=SUBSCRIPTION_ANALYSIS_AGENT)
    await runtime.run(selected)
    # Registry only contains account tools, which the selected subscription agent cannot use.
    assert provider.requests[0].tools == []
    assert provider.requests[0].messages[0].content == SUBSCRIPTION_ANALYSIS_AGENT.instructions


def test_tool_output_schema_describes_serialized_computed_fields():
    spec = create_app().state.tool_registry.get_by_name("get_category_breakdown")
    fields = spec.output_schema["$defs"]["CategorySpending"]["properties"]
    assert {"category_display", "share_display"} <= fields.keys()


@pytest.mark.parametrize("backend", ["manual", "langgraph"])
async def test_reasoning_continuation_and_call_identity_survive_tool_roundtrip(backend):
    runtime, provider = build_runtime(
        backend,
        [
            LLMResponse(
                reasoning_content="continuation",
                tool_calls=[LLMToolCall(id="read", name="list_accounts", arguments={})],
            ),
            LLMResponse(content="已查询"),
        ],
    )
    assert (await runtime.run(request())).answer == "本人账户：工资卡、储蓄卡、信用卡、旅行卡"
    messages = provider.requests[-1].messages
    assistant = next(m for m in messages if m.tool_calls)
    assert assistant.reasoning_content == "continuation"
    assert messages[-1].tool_call_id == assistant.tool_calls[0].id == "read"


def test_malformed_argument_json_is_preserved_for_model_repair():
    raw = '{"account_id":'
    wire = OpenAICompatibleProvider._message_to_wire(
        LLMMessage(
            role="assistant", tool_calls=[LLMToolCall(id="bad", name="get_balance", arguments=raw)]
        )
    )
    assert wire["tool_calls"][0]["function"]["arguments"] == raw


def test_duplicate_call_ids_and_invalid_names_are_rejected():
    with pytest.raises(ValidationError):
        LLMResponse(
            tool_calls=[
                LLMToolCall(id="same", name="list_accounts"),
                LLMToolCall(id="same", name="get_balance"),
            ]
        )
    with pytest.raises(ValidationError):
        LLMToolCall(id="bad", name="invalid.name")


@pytest.mark.parametrize("mutation", ["owner", "type", "payload", "approval", "consumption"])
async def test_workflow_tool_rejects_forged_operation_before_provider(app, mutation):
    _, provider, registry, engine = operation_runtime(app)
    ready = await authorize_workflow(app, engine)
    factory = app.state.test_session_factory
    async with factory() as session:
        created = await OperationService(session, app.state.event_bus, engine).prepare_transfer(
            ready.workflow_id, user_id=ready.user_id, expected_version=ready.version
        )
    async with factory() as session:
        operation = await session.get(OperationModel, created.operation_id)
        approval = await session.get(ApprovalModel, operation.approval_id)
        if mutation == "owner":
            operation.user_id = "foreign-user"
        elif mutation == "type":
            operation.operation_type = OperationType.SUBSCRIPTION_CANCEL
        elif mutation == "payload":
            operation.payload_json = {**operation.payload_json, "amount": "0.01"}
        elif mutation == "approval":
            approval.status = ApprovalStatus.APPROVED
        else:
            approval.consumed_by_operation_id = None
        await session.commit()
    provider.submit_transfer = AsyncMock(side_effect=AssertionError("must not submit"))
    spec = registry.get_by_name("commit_transfer")
    result = await ToolExecutor(registry, PolicyService()).execute(
        tool_name=spec.name,
        arguments={"operation_id": str(created.operation_id)},
        caller="workflow:transfer",
        principal=ExecutionPrincipal.for_workflow(ready.user_id),
        agent_allowlist=frozenset({spec.capability_id}),
    )
    assert result.ok and result.output["error_code"] == "OPERATION_NOT_FOUND"
    provider.submit_transfer.assert_not_awaited()


async def test_consumed_operation_authority_survives_expiry_for_recovery(app):
    _, _, _, engine = operation_runtime(app)
    ready = await authorize_workflow(app, engine)
    async with app.state.test_session_factory() as session:
        created = await OperationService(session, app.state.event_bus, engine).prepare_transfer(
            ready.workflow_id, user_id=ready.user_id, expected_version=ready.version
        )
    async with app.state.test_session_factory() as session:
        op = await session.get(OperationModel, created.operation_id)
        approval = await session.get(ApprovalModel, op.approval_id)
        approval.expires_at = datetime.now(UTC) - timedelta(days=1)
        await session.commit()
        assert (
            await authorized_operation(
                session, op.operation_id, ready.user_id, (OperationType.TRANSFER,)
            )
            is not None
        )


async def test_new_subscription_posting_is_in_model_tool_and_dashboard_analysis(
    app, client, monkeypatch
):
    import banking_api.api.routes.dashboard as dashboard
    import banking_api.tools.banking.get_spending_summary as summary_module

    bank, provider, clock, worker = subscription_runtime(app)
    app.state.mock_bank = bank
    app.state.transfer_provider = provider
    monkeypatch.setattr(dashboard, "reference_now", lambda: clock[0])
    monkeypatch.setattr(summary_module, "reference_now", lambda: clock[0])
    await worker.run_once()
    clock[0] = datetime(2026, 10, 8, 12, tzinfo=UTC)
    await worker.run_once()
    await worker.run_once()

    async def reader(user_id):
        async with app.state.test_session_factory() as session:
            rows = await AccountStatementService(bank, session).posted_transactions(
                user_id=user_id, as_of=clock[0]
            )
        return PostedAnalysisBank(bank, user_id, rows)

    spec = build_get_spending_summary_tool(FinancialAnalyticsService(bank), bank_reader=reader)
    result = await execute_spec(spec, {"month": "2026-10"})
    assert result.ok, result.error
    snapshot = (await client.get("/api/v1/dashboard", params={"month": "2026-10"})).json()
    assert result.output["total_spending"] == snapshot["spending"]["overview"]["total_spending"]
    assert result.output["spending_transaction_count"] == 1
    assert result.output["total_spending"] == "28.00"
