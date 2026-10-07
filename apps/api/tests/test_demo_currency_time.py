import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from test_plan_conditions import conditional_runtime
from test_transfer_workflow import build_transfer_runtime

from banking_api.application.conversation_service import ConversationService
from banking_api.application.task_service import TaskService
from banking_api.config.settings import Settings
from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.llm.models import LLMResponse
from banking_api.workflows.transfer.currency import canonicalize_currency
from banking_api.workflows.transfer.intent_extractor import TransferIntentExtractor


@pytest.mark.parametrize("alias", ["元", "人民币", "RMB", "CNY", "¥", "￥"])
async def test_currency_alias_is_grounded_and_workflow_red(app, client, alias):
    raw = f"从工资卡给李小雨转500{alias}"
    assert canonicalize_currency(alias, raw) == "CNY"
    responses = [
        LLMResponse(
            content=json.dumps(
                {"route": "TRANSFER_WORKFLOW", "requested_output": "WORKFLOW", "confidence": 0.99}
            )
        ),
        LLMResponse(
            content=json.dumps(
                {
                    "recipient_query": "李小雨",
                    "amount": "500",
                    "currency": alias,
                    "source_account_hint": "工资卡",
                }
            )
        ),
    ]
    runner, _, _, _ = build_transfer_runtime(app, responses)
    async with app.state.test_session_factory() as session:
        service = ConversationService(session, app.state.event_bus)
        conversation = await service.create(user_id="dev-user-001", title="币种")
        accepted = await service.accept_message(
            conversation_id=conversation.conversation_id, user_id="dev-user-001", content=raw
        )
    await runner.run(accepted.task_id)
    async with app.state.test_session_factory() as session:
        task = await TaskService(session).get(accepted.task_id, user_id="dev-user-001")
    workflow = (await client.get(f"/api/v1/workflows/{task.output['workflow_id']}")).json()
    assert workflow["status"] == "READY_FOR_REVIEW"
    assert workflow["risk_decision"]["currency"] == "CNY"
    assert workflow["risk_decision"]["level"] == "RED"


@pytest.mark.parametrize(
    "value,raw,expected",
    [
        ("USD", "转500美元", "USD"),
        ("EUR", "转500欧元", "EUR"),
        ("JPY", "转500日元", "JPY"),
        ("ABC", "转500ABC", "ABC"),
        (None, "转500", None),
        ("CNY", "转500", None),
    ],
)
def test_foreign_currency_not_silently_cny(value, raw, expected):
    assert canonicalize_currency(value, raw) == expected


@pytest.mark.parametrize(
    "value,raw",
    [
        ("CNY", "转500美元"),
        ("USD", "转500元"),
        ("USD", "转500"),
        ("神秘币", "转500神秘币"),
        ("CNY", "转500神秘币"),
        (None, "转500狗币"),
        ("CNY", "转500美元和600元"),
    ],
)
def test_unknown_or_contradictory_currency_fails_closed(value, raw):
    with pytest.raises(ValueError):
        canonicalize_currency(value, raw)


@pytest.mark.parametrize("alias", ["元", "人民币", "RMB", "CNY", "¥", "￥"])
async def test_alias_canonicalization_in_plan_path(app, client, alias):
    # The Plan uses the same original-message extraction boundary as direct routing.
    runner, _, _, _, task_id = await conditional_runtime(app, client, threshold="3000")
    provider = FakeLLMProvider(
        [
            LLMResponse(
                content=json.dumps(
                    {
                        "recipient_query": "李小雨",
                        "amount": "500",
                        "currency": alias,
                        "source_account_hint": "工资卡",
                    }
                )
            )
        ]
    )
    runner.transfer_intent_extractor = TransferIntentExtractor(provider)
    # CNY is grounded in the original Plan message; a model alias cannot change it.
    await runner.run(task_id)
    async with app.state.test_session_factory() as session:
        from sqlalchemy import select

        from banking_api.persistence.models import WorkflowModel

        workflow = await session.scalar(
            select(WorkflowModel).where(WorkflowModel.source_task_id == task_id)
        )
    assert workflow.state_json["review_payload"]["currency"] == "CNY"
    assert workflow.state_json["risk_decision"]["level"] == "RED"


def test_reference_clock_production_forbidden_and_requires_timezone():
    with pytest.raises(ValidationError, match="forbidden in production"):
        Settings(
            auth_mode="oidc",
            app_environment="production",
            oidc_issuer="https://issuer",
            oidc_audience="bank",
            demo_reference_time=datetime.now(UTC),
        )
    with pytest.raises(ValidationError, match="must include a timezone"):
        Settings(auth_mode="development", demo_reference_time=datetime(2026, 9, 28))
    assert Settings(auth_mode="development", demo_reference_time="").demo_reference_time is None
