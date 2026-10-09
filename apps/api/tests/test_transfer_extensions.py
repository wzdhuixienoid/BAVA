import json
from decimal import Decimal

import pytest
from banking_test_helpers import authenticate_workflow
from pydantic import ValidationError
from sqlalchemy import select
from test_transfer_authorization import create_ready_workflow, review_payload
from test_transfer_operations import operation_runtime

from banking_api.application.operation_service import OperationActionError, OperationService
from banking_api.application.workflow_service import WorkflowService
from banking_api.domain.enums import WorkflowStatus
from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.llm.models import LLMResponse
from banking_api.persistence.models import MockBankTransferModel, OperationModel
from banking_api.workflows.transfer.authorization import (
    canonicalize_transfer_payload,
    transfer_payload_hash,
)
from banking_api.workflows.transfer.intent_extractor import TransferIntentExtractor
from banking_api.workflows.transfer.models import SetRemarkAction


def test_remark_validation_and_legacy_hash():
    assert canonicalize_transfer_payload(review_payload()) == {
        "amount": "2000.00",
        "currency": "CNY",
        "payee_id": "payee_001",
        "source_account_id": "acc_salary",
    }
    assert transfer_payload_hash(review_payload()) != transfer_payload_hash(
        review_payload(remark="本月餐费")
    )
    assert SetRemarkAction(remark=" 餐费 ", expected_version=1).remark == "餐费"
    assert SetRemarkAction(remark="😀" * 100, expected_version=1).remark == "😀" * 100
    for invalid in ["😀" * 101, "备注\n", "\x00", "\u202e"]:
        with pytest.raises(ValidationError):
            SetRemarkAction(remark=invalid, expected_version=1)


async def test_remark_extraction():
    provider = FakeLLMProvider(
        [
            LLMResponse(
                content=json.dumps(
                    {"recipient_query": "张三", "amount": "100", "remark": "本月餐费"}
                )
            )
        ]
    )
    intent = await TransferIntentExtractor(provider).extract("给张三转100元，备注本月餐费")
    assert intent.remark == "本月餐费" and intent.amount == Decimal("100")


async def test_remark_mutation_revokes_authorization_and_persists_snapshot(app):
    _, provider, _, engine = operation_runtime(app)
    workflow = await create_ready_workflow(
        app, app.state.event_bus, engine, user_id="dev-user-001", amount=Decimal("1")
    )
    async with app.state.test_session_factory() as session:
        workflow = await WorkflowService(session, app.state.event_bus, engine).approve(
            workflow.workflow_id, user_id=workflow.user_id, expected_version=workflow.version
        )
    ready = await authenticate_workflow(app, engine, workflow)
    async with app.state.test_session_factory() as session:
        changed = await WorkflowService(session, app.state.event_bus, engine).set_remark(
            ready.workflow_id,
            user_id=ready.user_id,
            remark="<script>餐费</script>",
            expected_version=ready.version,
        )
    assert (
        changed.status is WorkflowStatus.READY_FOR_REVIEW and changed.state["authorization"] is None
    )
    async with app.state.test_session_factory() as session:
        with pytest.raises(OperationActionError):
            await OperationService(session, app.state.event_bus, engine).commit_workflow(
                changed.workflow_id, user_id=changed.user_id, expected_version=changed.version
            )
    async with app.state.test_session_factory() as session:
        changed = await WorkflowService(session, app.state.event_bus, engine).approve(
            changed.workflow_id, user_id=changed.user_id, expected_version=changed.version
        )
    ready = await authenticate_workflow(app, engine, changed)
    async with app.state.test_session_factory() as session:
        result = await OperationService(session, app.state.event_bus, engine).commit_workflow(
            ready.workflow_id, user_id=ready.user_id, expected_version=ready.version
        )
    async with app.state.test_session_factory() as session:
        operation = await session.get(OperationModel, result.operation_id)
        transfer = (await session.execute(select(MockBankTransferModel))).scalar_one()
        assert operation.payload_json["remark"] == transfer.remark == "<script>餐费</script>"
    assert await provider.transfer_count() == 1


