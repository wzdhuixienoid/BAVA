from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from banking_test_helpers import authenticate_workflow
from test_transfer_authorization import create_ready_workflow
from test_transfer_operations import operation_runtime

from banking_api.api.dependencies import get_current_principal
from banking_api.application.operation_service import OperationService
from banking_api.application.workflow_service import WorkflowService
from banking_api.domain.enums import OperationStatus
from banking_api.domain.principal import Principal
from banking_api.planning.models import ConditionDecision, ConditionPredicate


async def test_dashboard_transaction_filters_pagination_and_principal_scope(app, client):
    response = await client.get("/api/v1/dashboard/transactions", params={"limit": 5})
    assert response.status_code == 200
    page = response.json()
    assert len(page["transactions"]) == 5
    assert page["total_count"] > 100
    assert "2026-08" in page["available_months"]
    second = (
        await client.get("/api/v1/dashboard/transactions", params={"offset": 5, "limit": 5})
    ).json()
    assert not {row["transaction_id"] for row in page["transactions"]} & {
        row["transaction_id"] for row in second["transactions"]
    }
    accounts = app.state.mock_bank.list_accounts(user_id="dev-user-001")
    travel_id = next(
        account["account_id"] for account in accounts if account["display_name"] == "旅行卡"
    )
    filtered = await client.get(
        "/api/v1/dashboard/transactions",
        params={"year": 2026, "month_number": 8, "category": "TRAVEL", "account_id": travel_id},
    )
    assert filtered.status_code == 200
    rows = filtered.json()["transactions"]
    assert len(rows) == 6
    assert all(
        row["category"] == "TRAVEL" and row["account_id"] == travel_id and row["amount_display"]
        for row in rows
    )
    assert all(row["occurred_at"].startswith("2026-08") for row in rows)
    for params in (
        {"month": "2026-13"},
        {"year": 0},
        {"month_number": 13},
        {"offset": -1},
        {"limit": 101},
        {"account_id": "not-owned"},
    ):
        assert (
            await client.get("/api/v1/dashboard/transactions", params=params)
        ).status_code == 422
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="other-user", issuer="test", subject="other-user"
    )
    isolated = (await client.get("/api/v1/dashboard/transactions")).json()
    assert isolated["transactions"] == [] and isolated["total_count"] == 0
    assert isolated["available_months"] == [] and isolated["available_categories"] == []


async def test_dashboard_reuses_existing_analysis_and_scoped_live_balance(app, client):
    bank, provider, _, engine = operation_runtime(app)
    app.state.mock_bank = bank
    app.state.transfer_provider = provider
    response = await client.get("/api/v1/dashboard", params={"month": "2026-08"})
    assert response.status_code == 200
    snapshot = response.json()
    assert snapshot["accounts"][0]["balance_display"] == "¥23,864.52"
    assert snapshot["spending"]["period"] == "2026-08"
    assert snapshot["spending"]["overview"]["total_spending_display"]
    assert snapshot["spending"]["category_breakdown"]
    assert snapshot["spending"]["top_transactions"]
    recent = snapshot["recent_transactions"]
    assert 5 < len(recent) <= 100
    assert all(item["amount_display"] and item["currency"] for item in recent)
    assert all(
        item["account_id"] in {a["account_id"] for a in snapshot["accounts"]} for item in recent
    )
    assert [item["occurred_at"] for item in recent] == sorted(
        (item["occurred_at"] for item in recent), reverse=True
    )
    for item in snapshot["subscriptions"]["subscriptions"]:
        assert item["monthly_cost_display"]
        assert item["annual_projected_cost_display"]
        if item["management_type"] == "DETECTED_ONLY":
            assert item["cancellable"] is False
    workflow = await create_ready_workflow(
        app, app.state.event_bus, engine, user_id="dev-user-001", amount=Decimal("500")
    )
    async with app.state.test_session_factory() as session:
        ready = await WorkflowService(session, app.state.event_bus, engine).approve(
            workflow.workflow_id, user_id=workflow.user_id, expected_version=workflow.version
        )
    ready = await authenticate_workflow(app, engine, ready)
    async with app.state.test_session_factory() as session:
        operation = await OperationService(session, app.state.event_bus, engine).commit_workflow(
            ready.workflow_id, user_id=ready.user_id, expected_version=ready.version
        )
    assert operation.status is OperationStatus.SUCCEEDED
    fresh = (await client.get("/api/v1/dashboard")).json()
    assert fresh["accounts"][0]["balance"] == "23364.52"
    assert fresh["accounts"][0]["balance_display"] == "¥23,364.52"
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="other-user", issuer="test", subject="other-user"
    )
    isolated = await client.get("/api/v1/dashboard")
    assert isolated.status_code == 422
    assert "23864.52" not in isolated.text
    assert "23364.52" not in isolated.text


async def test_workflow_projection_requires_workflow_and_operation_success(app):
    _, _, _, engine = operation_runtime(app)
    workflow = await create_ready_workflow(
        app, app.state.event_bus, engine, user_id="dev-user-001", amount=Decimal("600")
    )
    async with app.state.test_session_factory() as session:
        ready = await WorkflowService(session, app.state.event_bus, engine).get(
            workflow.workflow_id, user_id=workflow.user_id
        )
    assert ready.presentation.business_success is False
    assert ready.presentation.amount_display == "¥600.00"
    assert ready.presentation.approval_required is True
    assert ready.presentation.reauthentication_required is True
    assert (
        next(stage for stage in ready.presentation.stages if stage.key == "approval").status
        == "WAITING_USER"
    )
    assert (
        next(stage for stage in ready.presentation.stages if stage.key == "final").status
        == "PENDING"
    )
    assert ready.state["risk_decision"]["requested_amount_display"] == "¥600.00"


def test_condition_display_does_not_recalculate_outcome():
    decision = ConditionDecision(
        predicate=ConditionPredicate.ACCOUNT_BALANCE_AT_LEAST,
        source_step_id=uuid4(),
        source_output_hash="a" * 64,
        actual_value="5000",
        threshold_value="4000",
        currency="CNY",
        outcome="FALSE",
        evaluated_at=datetime.now(UTC),
    )
    assert decision.outcome == "FALSE"
    assert decision.actual_display == "¥5,000.00"
    assert decision.threshold_display == "¥4,000.00"
