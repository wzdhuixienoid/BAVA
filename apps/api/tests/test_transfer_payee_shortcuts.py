from datetime import UTC, datetime
from decimal import Decimal

import pytest
from banking_test_helpers import authenticate_workflow
from sqlalchemy import func, select
from test_transfer_operations import operation_runtime

from banking_api.application.conversation_service import ConversationService
from banking_api.application.workflow_service import WorkflowService
from banking_api.domain.enums import TaskStatus, WorkflowStatus
from banking_api.persistence.models import OperationModel, TaskModel, WorkflowModel
from banking_api.workflows.transfer.models import TransferIntent


async def create_draft(app, intent):
    _, _, _, engine = operation_runtime(app)
    async with app.state.test_session_factory() as session:
        conversation = await ConversationService(session, app.state.event_bus).create(
            user_id="dev-user-001", title="收款人快捷选择验收"
        )
        accepted = await ConversationService(session, app.state.event_bus).accept_message(
            conversation_id=conversation.conversation_id, user_id="dev-user-001", content="转账"
        )
        workflow = await WorkflowService(session, app.state.event_bus, engine).create_transfer(
            user_id="dev-user-001",
            conversation_id=conversation.conversation_id,
            source_task_id=accepted.task_id,
            intent=intent,
        )
    return engine, workflow


async def test_existing_payee_selection_from_missing_name_is_atomic_and_owner_checked(app, client):
    _, workflow = await create_draft(
        app, TransferIntent(amount=Decimal("1"), source_account_hint="工资卡")
    )
    assert workflow.status is WorkflowStatus.WAITING_FOR_INPUT
    path = f"/api/v1/workflows/{workflow.workflow_id}/actions/select-payee"
    invalid = await client.post(
        path,
        json={
            "payee_id": "another-user-payee",
            "recipient_query": "张三",
            "expected_version": workflow.version,
        },
    )
    assert invalid.status_code == 422
    response = await client.post(
        path,
        json={
            "payee_id": "payee_002",
            "recipient_query": "张三",
            "expected_version": workflow.version,
        },
    )
    assert response.status_code == 200
    selected = response.json()
    assert selected["status"] == "READY_FOR_REVIEW"
    assert selected["state"]["review_payload"]["payee_id"] == "payee_002"
    assert selected["risk_level"] == "YELLOW" and selected["approval_summary"] is None
    assert (
        await client.post(
            path,
            json={
                "payee_id": "payee_001",
                "recipient_query": "张三",
                "expected_version": workflow.version,
            },
        )
    ).status_code == 409
    async with app.state.test_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(OperationModel)) == 0


async def test_new_payee_can_be_selected_after_no_match(app, client):
    _, workflow = await create_draft(
        app,
        TransferIntent(recipient_query="新朋友", amount=Decimal("1"), source_account_hint="工资卡"),
    )
    assert workflow.status is WorkflowStatus.WAITING_FOR_INPUT
    payee = (
        await client.post(
            "/api/v1/payees",
            json={
                "display_name": "新朋友",
                "bank_name": "森林银行（虚构）",
                "account_number": "6222021234568686",
                "confirmed": True,
            },
        )
    ).json()
    selected = await client.post(
        f"/api/v1/workflows/{workflow.workflow_id}/actions/select-payee",
        json={
            "payee_id": payee["payee_id"],
            "recipient_query": "新朋友",
            "expected_version": workflow.version,
        },
    )
    assert selected.status_code == 200
    assert selected.json()["state"]["review_payload"]["payee_id"] == payee["payee_id"]


@pytest.mark.parametrize("deleted", [False, True])
async def test_legacy_unmatched_draft_can_recover_except_in_deleted_conversation(
    app, client, deleted
):
    _, workflow = await create_draft(
        app,
        TransferIntent(recipient_query="不存在", amount=Decimal("1"), source_account_hint="工资卡"),
    )
    async with app.state.test_session_factory() as session:
        row = await session.get(WorkflowModel, workflow.workflow_id)
        state = dict(row.state_json)
        state["required_input"] = None
        state["validation"] = {
            "is_valid": False,
            "validated_at": datetime.now(UTC).isoformat(),
            "issues": [{"code": "PAYEE_NOT_FOUND", "message": "未找到匹配的收款人"}],
        }
        row.state_json = state
        row.status = WorkflowStatus.FAILED
        task = await session.get(TaskModel, workflow.source_task_id)
        task.status = TaskStatus.COMPLETED
        await session.commit()
    if deleted:
        assert (
            await client.delete(f"/api/v1/conversations/{workflow.conversation_id}")
        ).status_code == 204
    selected = await client.post(
        f"/api/v1/workflows/{workflow.workflow_id}/actions/select-payee",
        json={
            "payee_id": "payee_003",
            "recipient_query": "李小雨",
            "expected_version": workflow.version,
        },
    )
    assert selected.status_code == (404 if deleted else 200)
    if not deleted:
        assert selected.json()["status"] == "READY_FOR_REVIEW"
        assert selected.json()["state"]["validation"]["is_valid"]


async def test_shortcut_changing_payee_invalidates_previous_confirmation_and_verification(
    app, client
):
    engine, workflow = await create_draft(
        app,
        TransferIntent(
            recipient_query="李小雨", amount=Decimal("2000"), source_account_hint="工资卡"
        ),
    )
    async with app.state.test_session_factory() as session:
        workflow = await WorkflowService(session, app.state.event_bus, engine).approve(
            workflow.workflow_id, user_id=workflow.user_id, expected_version=workflow.version
        )
    workflow = await authenticate_workflow(app, engine, workflow)
    assert workflow.status is WorkflowStatus.READY_FOR_COMMIT
    response = await client.post(
        f"/api/v1/workflows/{workflow.workflow_id}/actions/select-payee",
        json={
            "payee_id": "payee_002",
            "recipient_query": "张三",
            "expected_version": workflow.version,
        },
    )
    assert response.status_code == 200
    changed = response.json()
    assert changed["status"] == "READY_FOR_REVIEW"
    assert changed["state"]["authorization"] is None
    assert changed["approval_summary"]["status"] == "INVALIDATED"
    assert changed["reauth_summary"]["status"] == "INVALIDATED"
