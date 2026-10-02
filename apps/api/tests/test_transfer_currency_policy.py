import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from test_plans import call, get_plan, proposal, setup_plan
from test_transfer_authorization import create_ready_workflow
from test_transfer_operations import operation_runtime

from banking_api.application.conversation_service import ConversationService
from banking_api.application.operation_service import OperationActionError, OperationService
from banking_api.application.workflow_service import WorkflowActionError, WorkflowService
from banking_api.domain.enums import ApprovalStatus, WorkflowStatus
from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.llm.models import LLMResponse
from banking_api.persistence.models import (
    ApprovalModel,
    MockBankTransferModel,
    OperationModel,
    ReauthenticationModel,
    WorkflowModel,
)
from banking_api.workflows.transfer.authorization import transfer_payload_hash
from banking_api.workflows.transfer.intent_extractor import TransferIntentExtractor
from banking_api.workflows.transfer.models import TransferIntent, TransferWorkflowState
from banking_api.workflows.transfer.risk import (
    TransferRiskCurrencyUnsupportedError,
    TransferRiskPolicy,
)

UNSUPPORTED = "TRANSFER_RISK_CURRENCY_UNSUPPORTED"


def add_usd_account(bank):
    bank._accounts.append(
        {
            "user_id": "dev-user-001",
            "account_id": "acc_usd",
            "display_name": "美元卡",
            "account_type": "DEBIT",
            "masked_number": "****7788",
            "currency": "USD",
            "status": "ACTIVE",
            "balance": "23864.52",
        }
    )


async def assert_no_write_facts(app, provider):
    async with app.state.test_session_factory() as session:
        for model in (OperationModel, MockBankTransferModel, ApprovalModel, ReauthenticationModel):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
    assert await provider.transfer_count() == 0


@pytest.mark.parametrize("currency", ["USD", "EUR", "", "cny"])
def test_risk_policy_rejects_unsupported_currency_without_a_decision(currency):
    with pytest.raises(TransferRiskCurrencyUnsupportedError) as error:
        TransferRiskPolicy().evaluate(
            requested_amount=Decimal("500.00"),
            currency=currency,
            business_date=datetime.now(UTC).date(),
            successful_transfer_total_today=Decimal("0"),
            in_flight_transfer_exposure_today=Decimal("0"),
            evaluated_at=datetime.now(UTC),
        )
    assert error.value.code == UNSUPPORTED


@pytest.mark.parametrize(
    "account_currency,expected_code",
    [
        ("CNY", "CURRENCY_MISMATCH"),
        ("USD", UNSUPPORTED),
    ],
)
async def test_currency_rejection_is_visible_and_has_no_financial_side_effects(
    app, client, account_currency, expected_code
):
    bank, provider, _, engine = operation_runtime(app)
    if account_currency == "USD":
        add_usd_account(bank)
    async with app.state.test_session_factory() as session:
        service = ConversationService(session, app.state.event_bus)
        conversation = await service.create(user_id="dev-user-001", title="币种边界")
        task = await service.accept_message(
            conversation_id=conversation.conversation_id,
            user_id="dev-user-001",
            content="转账500美元",
        )
        workflow = await WorkflowService(session, app.state.event_bus, engine).create_transfer(
            user_id="dev-user-001",
            conversation_id=conversation.conversation_id,
            source_task_id=task.task_id,
            intent=TransferIntent(
                recipient_query="李小雨",
                amount=Decimal("500.00"),
                currency="USD",
                source_account_hint="美元卡" if account_currency == "USD" else "工资卡",
            ),
        )
    assert workflow.status is WorkflowStatus.FAILED
    assert workflow.state["validation"]["issues"][0]["code"] == expected_code
    assert workflow.risk_decision is None
    assert workflow.state["review_payload"] is None
    api_workflow = (await client.get(f"/api/v1/workflows/{workflow.workflow_id}")).json()
    assert api_workflow["state"]["validation"]["issues"][0]["code"] == expected_code
    for action in ("approve", "start-reauth", "commit"):
        response = await client.post(
            f"/api/v1/workflows/{workflow.workflow_id}/actions/{action}",
            json={"expected_version": workflow.version},
        )
        assert response.status_code == 422
    await assert_no_write_facts(app, provider)
    assert await provider.effective_balance("dev-user-001", "acc_salary") == Decimal("23864.52")


async def test_legacy_usd_authorization_cannot_create_operation_or_reauthentication(app, client):
    bank, provider, _, engine = operation_runtime(app)
    add_usd_account(bank)
    workflow = await create_ready_workflow(
        app, app.state.event_bus, engine, user_id="dev-user-001", amount=Decimal("500.00")
    )
    async with app.state.test_session_factory() as session:
        ready = await WorkflowService(session, app.state.event_bus, engine).approve(
            workflow.workflow_id, user_id=workflow.user_id, expected_version=workflow.version
        )
    # Simulate a pre-policy USD review and matching approval, so hash binding is not the guard.
    async with app.state.test_session_factory() as session:
        model = await session.get(WorkflowModel, ready.workflow_id)
        state = TransferWorkflowState.model_validate(model.state_json)
        state.draft.source_account_id = "acc_usd"
        state.draft.currency = "USD"
        state.review_payload.source_account_id = "acc_usd"
        state.review_payload.currency = "USD"
        approval = await session.get(ApprovalModel, state.authorization.approval_id)
        approval.payload_hash = transfer_payload_hash(state.review_payload)
        state.authorization.approval_payload_hash = approval.payload_hash
        model.state_json = state.model_dump(mode="json")
        await session.commit()
    async with app.state.test_session_factory() as session:
        with pytest.raises(OperationActionError, match=UNSUPPORTED):
            await OperationService(session, app.state.event_bus, engine).prepare_transfer(
                ready.workflow_id, user_id=ready.user_id, expected_version=ready.version
            )
    response = await client.post(
        f"/api/v1/workflows/{ready.workflow_id}/actions/commit",
        json={"expected_version": ready.version},
    )
    assert response.status_code == 422 and response.json()["detail"] == UNSUPPORTED
    async with app.state.test_session_factory() as session:
        model = await session.get(WorkflowModel, ready.workflow_id)
        model.status = WorkflowStatus.REAUTH_REQUIRED
        await session.commit()
    async with app.state.test_session_factory() as session:
        with pytest.raises(WorkflowActionError, match=UNSUPPORTED):
            await WorkflowService(session, app.state.event_bus, engine).start_reauthentication(
                ready.workflow_id, user_id=ready.user_id, expected_version=ready.version
            )
    async with app.state.test_session_factory() as session:
        approval = await session.get(ApprovalModel, ready.approval_summary.approval_id)
        assert approval.status is ApprovalStatus.APPROVED
        assert approval.consumed_at is None
        for model in (OperationModel, MockBankTransferModel, ReauthenticationModel):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
    assert await provider.transfer_count() == 0


async def test_complex_plan_transfer_uses_same_currency_policy(app, client):
    runner, _, _, _, task_id = await setup_plan(
        app,
        client,
        data=proposal(["ACCOUNT_QUERY", "TRANSFER_WORKFLOW"]),
        responses=[
            call("get_balance", {"account_id": "acc_salary"}),
            LLMResponse(content="已查询"),
        ],
        user_request="查余额后给李小雨从美元卡转500美元",
    )
    bank, provider, _, engine = operation_runtime(app)
    add_usd_account(bank)
    runner.transfer_workflow_engine = engine
    runner.transfer_intent_extractor = TransferIntentExtractor(
        FakeLLMProvider(
            [
                LLMResponse(
                    content=json.dumps(
                        {
                            "recipient_query": "李小雨",
                            "amount": "500.00",
                            "currency": "USD",
                            "source_account_hint": "美元卡",
                        }
                    )
                ),
            ]
        )
    )
    await runner.run(task_id)
    plan = await get_plan(app, task_id)
    assert plan.status == "FAILED"
    assert plan.steps[0].status == "COMPLETED"
    assert plan.steps[1].status == "FAILED"
    workflow = (await client.get(f"/api/v1/workflows/{plan.steps[1].linked_workflow_id}")).json()
    assert workflow["status"] == "FAILED"
    assert workflow["state"]["validation"]["issues"][0]["code"] == UNSUPPORTED
    await assert_no_write_facts(app, provider)
