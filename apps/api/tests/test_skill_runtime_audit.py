"""Skill selection and trade fallback regressions on isolated owner data."""

from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_wealth import USER
from test_wealth import wealth as wealth
from test_wealth_repairs import reassemble
from test_wealth_v0113 import result

from banking_api.agent_skills import AgentSkillCatalog
from banking_api.application.conversation_service import ConversationService
from banking_api.domain.enums import RuntimeBackend, TaskStatus
from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.persistence.models import MessageModel, OperationModel, TaskModel, WorkflowModel
from banking_api.routing.request_router import RequestRouter
from banking_api.skills.wealth_recommendation import WealthRecommendationSkill
from banking_api.wealth.answer import apply_answer


@pytest.mark.parametrize(
    "text,needs_shares",
    [
        ("用工资卡赎回演示均衡优选10.123456份", False),
        ("用工资卡全部赎回演示均衡优选", False),
        ("用工资卡赎回演示均衡优选", True),
        ("用工资卡赎回演示均衡优选1000元", True),
    ],
)
async def test_redemption_fallback_uses_shares_not_purchase_budget(wealth, text, needs_shares):
    # Redemption does not require a new purchase risk assessment.
    analysis = await result(wealth, text)
    assert analysis.result_kind == "PREPARE_REDEEM"
    assert analysis.status != "NEEDS_ASSESSMENT"
    # A historical recommendation budget must not reappear as a redemption amount.
    analysis.needs.amount = "5000"
    response = WealthRecommendationSkill().present(analysis)
    assert "申购" not in response.headline + "".join(response.questions)
    assert "付款账户" not in "".join(response.questions)
    assert response.budget_display is None
    assert bool(response.questions) is needs_shares
    if needs_shares:
        assert "份" in response.questions[0]
    skill = AgentSkillCatalog().activate("PREPARE_REDEEM")
    answer = apply_answer(analysis, "", skill).answer
    assert analysis.customer_response.budget_display is None
    assert answer.skill_resource_hashes == skill.resources
    assert answer.workflow_id is None


@pytest.mark.parametrize("explicit", ["$unknown-skill", "$wealth-trade-assistance"])
async def test_http_wrong_skill_returns_validation_error_without_financial_writes(
    wealth, monkeypatch, explicit
):
    app, _ = reassemble(wealth, monkeypatch, True)
    app.state.llm_provider = FakeLLMProvider([])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/wealth/analysis",
            json={
                "intent": "COMPARISON",
                "product_ids": ["mock-wealth-03", "mock-wealth-04"],
                "query": f"{explicit} 比较演示稳健优选和演示均衡优选",
            },
        )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_SKILL_SELECTION"
    async with wealth[0]() as session:
        assert await session.scalar(select(func.count()).select_from(OperationModel)) == 0
        assert await session.scalar(select(func.count()).select_from(WorkflowModel)) == 0


async def test_conversation_wrong_skill_completes_with_explanation_instead_of_internal_failure(
    wealth, monkeypatch
):
    app, _ = reassemble(wealth, monkeypatch, True)
    runner = app.state.task_runner
    runner.router = RequestRouter(FakeLLMProvider([]))
    runner.wealth_clock = wealth[1]
    async with wealth[0]() as session:
        service = ConversationService(session, runner.bus, runtime_backend=RuntimeBackend.LANGGRAPH)
        conversation = await service.create(user_id=USER, title="skill selection")
        accepted = await service.accept_message(
            conversation_id=conversation.conversation_id,
            user_id=USER,
            content="$wealth-trade-assistance 比较演示均衡优选和演示均衡周享",
        )
    await runner.run(accepted.task_id)
    async with wealth[0]() as session:
        task = await session.get(TaskModel, accepted.task_id)
        assert task.status == TaskStatus.COMPLETED.value
        message = await session.get(MessageModel, UUID(task.output_json["assistant_message_id"]))
        assert "不匹配" in message.content
        assert await session.scalar(select(func.count()).select_from(OperationModel)) == 0
        assert await session.scalar(select(func.count()).select_from(WorkflowModel)) == 0
