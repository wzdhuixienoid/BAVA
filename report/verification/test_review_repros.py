"""Reproduce review findings without a real LLM, banking write, or Demo DB.

These tests assert the OBSERVED defects, so PASS means reproduction succeeded.
Run from apps/api with PYTHONPATH=tests, -c pyproject.toml, and this file as target.
"""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from banking_api.application.workflow_service import WorkflowService
from banking_api.domain.event import Event
from banking_api.domain.principal import ExecutionPrincipal
from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.llm.models import LLMResponse
from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import ReauthenticationModel, SecurityGuardStateModel
from banking_api.planning.constraints import has_conditional_control
from banking_api.planning.planner import ConstrainedPlanner
from banking_api.planning.validator import PlanValidationError
from banking_api.policy.service import PolicyService
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.runtime.event_bus import EventBus
from banking_api.tools.banking import (
    build_get_balance_tool,
    build_list_accounts_tool,
    build_search_payees_tool,
)
from banking_api.tools.executor import ToolExecutor
from banking_api.workflows.transfer.engine import TransferWorkflowEngine
from banking_api.workflows.transfer.intent_extractor import TransferIntentExtractor
from conftest import app  # noqa: F401 -- reuse isolated SQLite fixture
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_transfer_authorization import create_ready_workflow


async def test_r01_unicode_otp_http_500_and_no_failure_counter(app):  # noqa: F811 -- pytest fixture
    bus = EventBus()
    bank = MockBankService()
    registry = ToolRegistry()
    for tool in (
        build_list_accounts_tool(bank),
        build_get_balance_tool(bank),
        build_search_payees_tool(bank),
    ):
        registry.register(tool)
    engine = TransferWorkflowEngine(ToolExecutor(registry, PolicyService()))
    workflow = await create_ready_workflow(app, bus, engine, user_id="dev-user-001")
    async with app.state.test_session_factory() as session:
        workflow = await WorkflowService(session, bus, engine).approve(
            workflow.workflow_id,
            user_id=workflow.user_id,
            expected_version=workflow.version,
        )
    async with app.state.test_session_factory() as session:
        workflow = await WorkflowService(session, bus, engine).start_reauthentication(
            workflow.workflow_id,
            user_id=workflow.user_id,
            expected_version=workflow.version,
        )
    app.state.transfer_workflow_engine = engine
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        responses = []
        for _ in range(3):
            response = await client.post(
                f"/api/v1/workflows/{workflow.workflow_id}/actions/verify-reauth",
                json={
                    "reauth_id": str(workflow.reauth_summary.reauth_id),
                    "verification_code": "错误验证码",
                    "expected_version": workflow.version,
                },
            )
            responses.append(response.status_code)
    async with app.state.test_session_factory() as session:
        challenge = await session.get(ReauthenticationModel, workflow.reauth_summary.reauth_id)
        guards = list((await session.execute(select(SecurityGuardStateModel))).scalars())
    assert responses == [500, 500, 500]
    assert challenge.attempt_count == 0
    assert not guards or all(guard.reauth_failure_count == 0 for guard in guards)
    print("R01: HTTP", responses, "; challenge attempts=0; no failure lock")


def _unguarded_proposal():
    return json.dumps(
        {
            "goal_summary": "查询余额，然后转账",
            "steps": [
                {
                    "kind": "CAPABILITY",
                    "step_key": "balance",
                    "display_title": "查询工资卡余额",
                    "capability": "ACCOUNT_QUERY",
                    "depends_on": [],
                    "subtask_query": "工资卡余额多少？",
                },
                {
                    "kind": "CAPABILITY",
                    "step_key": "transfer",
                    "display_title": "创建转账流程",
                    "capability": "TRANSFER_WORKFLOW",
                    "depends_on": ["balance"],
                },
            ],
        },
        ensure_ascii=False,
    )


async def test_r02_only_if_chinese_allows_omitted_condition():
    original = "只有工资卡余额不少于30000元，才从工资卡给李小雨转500元。"
    assert has_conditional_control(original) is False
    planner = ConstrainedPlanner(FakeLLMProvider([LLMResponse(content=_unguarded_proposal())]))
    plan = await planner.propose(original)
    assert len(plan.proposal.steps) == 2
    assert plan.proposal.steps[-1].guard_condition_step_key is None
    print("R02: 只有...才... accepted an unguarded transfer plan")
    # Control: the recognized equivalent is rejected with the same bad model proposal.
    planner = ConstrainedPlanner(FakeLLMProvider([LLMResponse(content=_unguarded_proposal())]))
    with pytest.raises(PlanValidationError):
        await planner.propose("如果工资卡余额不少于30000元，就从工资卡给李小雨转500元。")


@pytest.mark.parametrize("literal", ["500瑞士法郎", "$500"])
async def test_r03_unrecognized_currency_defaults_to_cny_draft(literal):
    original = f"从工资卡给李小雨转{literal}。"
    provider = FakeLLMProvider(
        [
            LLMResponse(
                content=json.dumps(
                    {
                        "recipient_query": "李小雨",
                        "amount": "500",
                        "currency": None,
                        "source_account_hint": "工资卡",
                    },
                    ensure_ascii=False,
                )
            )
        ]
    )
    intent = await TransferIntentExtractor(provider).extract(original)
    assert intent.currency is None
    bank = MockBankService()
    registry = ToolRegistry()
    for tool in (
        build_list_accounts_tool(bank),
        build_get_balance_tool(bank),
        build_search_payees_tool(bank),
    ):
        registry.register(tool)
    engine = TransferWorkflowEngine(ToolExecutor(registry, PolicyService()))
    status, state = await engine.start(
        intent, principal=ExecutionPrincipal.for_workflow("dev-user-001")
    )
    assert status.value == "READY_FOR_REVIEW"
    assert state.review_payload.currency == "CNY"
    print(f"R03: {literal} -> READY_FOR_REVIEW 500 CNY (no Operation created)")


async def test_k01_process_local_event_bus_has_no_cross_process_delivery():
    first, second = EventBus(), EventBus()
    conversation_id = uuid4()
    event = Event(
        event_id=uuid4(),
        event_type="task.completed",
        timestamp=datetime.now(UTC),
        conversation_id=conversation_id,
        task_id=uuid4(),
        sequence=1,
        data={},
    )
    async with second.subscribe(conversation_id) as queue:
        await first.publish(event)
        assert queue.empty()
    print("K01: publisher on EventBus A does not notify subscribers on B")
