"""Positive regressions for v0.11.3, with isolated financial fixtures."""

import json
from pathlib import Path

import pytest
from test_wealth import USER
from test_wealth import wealth as wealth
from test_wealth_repairs import assessment

from banking_api.agent_skills import AgentSkillCatalog
from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.llm.models import LLMResponse
from banking_api.wealth.advisory import WealthAdvisoryService
from banking_api.wealth.answer import apply_answer
from banking_api.wealth.coordination import analysis_request
from banking_api.wealth.intent import extract_quantity
from banking_api.wealth.quantity_parser import quantities
from banking_api.wealth.semantic import fallback_frame, interpret
from banking_api.wealth.service import WealthService


@pytest.mark.parametrize(
    "original,value",
    [
        ("5千", "5000"),
        ("五千", "5000"),
        ("5k", "5000"),
        ("5K", "5000"),
        ("0.5万", "5000.0"),
        ("1.5万元", "15000.0"),
        ("￥5,000", "5000"),
        ("两千元", "2000"),
        ("三千五百元", "3500"),
        ("1亿元", "100000000"),
    ],
)
def test_exact_shared_money(original, value):
    found = quantities("预算" + original)
    assert len(found) == 1 and found[0].value == value
    assert extract_quantity("申购" + original, "PURCHASE").quantity == value


@pytest.mark.parametrize("text", ["5xyz", "R4", "10%", "2026-10-11", "持有30天", "半年"])
def test_non_money_never_becomes_budget(text):
    assert not quantities(text)


@pytest.mark.parametrize("text", ["约五千到一万元", "不超过5000元", "最多5千", "五千左右"])
def test_ranges_not_transaction_authority(text):
    assert extract_quantity("申购" + text, "PURCHASE").quantity is None


def test_multiple_money_roles():
    values = quantities("有5000元，其中1000元留作应急")
    assert [(v.value, v.role) for v in values] == [("5000", "BUDGET"), ("1000", "RESERVE")]


async def test_model_spans_and_units_are_verified():
    frame = {"action": "RECOMMEND", "quantity_mentions": [{"original": "5千", "role": "BUDGET"}]}
    result = await interpret(
        FakeLLMProvider([LLMResponse(content=json.dumps(frame))]), "预算5千推荐理财"
    )
    assert result.generation_source == "MODEL_EXTRACTED"
    assert result.quantity_mentions[0].value == "5000"
    malicious = {
        "action": "PREPARE_PURCHASE",
        "product_mentions": ["别人的产品"],
        "quantity_mentions": [{"original": "500000元"}],
    }
    result = await interpret(
        FakeLLMProvider([LLMResponse(content=json.dumps(malicious))] * 2), "预算5千推荐理财"
    )
    assert result.generation_source == "DETERMINISTIC_FALLBACK"
    assert result.quantity_mentions[0].value == "5000"


async def result(wealth, text, previous=None, frame=None):
    factory, clock, balances, *_ = wealth
    async with factory() as session:
        svc = WealthService(session, balances, clock)
        frame = frame or fallback_frame(text, previous)
        body = analysis_request(
            frame,
            await svc.products(USER),
            previous,
            svc.balances._bank.list_accounts(user_id=USER),
        )
        return await WealthAdvisoryService(svc).analyze(USER, body, previous)


async def test_positive_budget_goal_loss_and_conservative_default(wealth):
    await assessment(wealth)
    r = await result(wealth, "我预算5千，想要赚钱，可接受部分亏损，有什么适合我的产品吗")
    assert r.needs.amount == "5000" and r.candidates and r.status == "CONDITIONAL"
    assert r.needs.return_goal and r.needs.loss_tolerance_raw
    assert r.candidates[0].product.risk == "R1"
    assert "问卷目标" not in r.conclusion and "没有说明" not in r.conclusion


async def test_loss_update_clears_prior_no_loss_without_changing_assessment(wealth):
    await assessment(wealth)
    first = await result(wealth, "不能亏本金")
    assert first.status == "NO_MATCH"
    second = await result(wealth, "改一下，我可以承担部分本金损失，最多10%", first)
    assert not second.needs.constraints.no_principal_loss
    assert second.candidates and second.assessment_id == first.assessment_id
    assert second.needs.constraints.preferred_risk is None


async def test_purchase_stage_only_trade_fields_and_continuation(wealth):
    await assessment(wealth)
    r = await result(wealth, "预算5千，推荐理财")
    p = await result(wealth, "我要购买演示均衡优选", r)
    assert p.result_kind == "PREPARE_PURCHASE" and len(p.candidates) == 1
    assert p.customer_response.questions == ["请选择本人付款账户。"]
    q = await result(wealth, "用工资卡，买三千元", p)
    assert q.intent_frame.action == "PREPARE_PURCHASE" and q.needs.amount == "3000"
    assert q.needs.account_id and q.candidates[0].product.product_id == "mock-wealth-04"


@pytest.mark.parametrize(
    "text",
    [
        "从工资卡购买演示均衡优选5000元",
        "用工资卡购买演示均衡优选5000元",
        "预算5000元，从工资卡购买演示均衡优选",
    ],
)
async def test_complete_buy_equivalent(wealth, text):
    await assessment(wealth)
    r = await result(wealth, text)
    assert r.intent_frame.action == "PREPARE_PURCHASE"
    assert r.needs.amount == "5000" and r.needs.account_id
    assert r.candidates[0].product.product_id == "mock-wealth-04"


async def test_new_generated_prose_not_block_permutation(wealth):
    await assessment(wealth)
    r = await result(wealth, "预算五千，推荐理财")
    skill = AgentSkillCatalog().activate("RECOMMEND")
    c = r.candidates[0]
    original = "这笔钱可以用来尝试净值投资，但短期用款与追求收益需要分别考虑。"
    raw = json.dumps(
        {
            "headline": original,
            "paragraphs": [
                {
                    "block_id": "new-explanation",
                    "title": "取舍",
                    "text": "先了解{{" + c.fact_id + ".name}}的窗口，本金仍可能损失。",
                    "fact_ids": [c.fact_id],
                    "evidence_ids": c.evidence_ids[:1],
                }
            ],
            "questions": ["这笔钱什么时候可能需要用？"],
            "relations": [],
        }
    )
    out = apply_answer(r, raw, skill)
    assert out.answer.generation_source == "MODEL_GENERATED"
    assert out.customer_response.headline == original and original not in [
        b.text for b in r.blocks[1:]
    ]
    assert "{{" not in out.blocks[1].text


@pytest.mark.parametrize(
    "bad",
    [
        {"headline": "保证本金不亏"},
        {"headline": "申购费99元"},
        {"headline": "风险R5最适合购买"},
        {"relations": ["LOWER_TOTAL_FEE:fake:fake"]},
        {"paragraphs": [{"block_id": "x", "title": "x", "text": "x", "evidence_ids": ["fake"]}]},
    ],
)
async def test_tampered_contract_falls_back_without_write(wealth, bad):
    await assessment(wealth)
    r = await result(wealth, "预算五千，推荐理财")
    raw = json.dumps(
        {"headline": "先了解产品", "paragraphs": [], "questions": [], "relations": [], **bad}
    )
    r = apply_answer(r, raw, AgentSkillCatalog().activate("RECOMMEND"))
    assert r.answer.generation_source == "DETERMINISTIC_FALLBACK" and r.candidates
    assert r.answer.workflow_id is None


def test_skill_modes_resources_and_path_boundary(tmp_path):
    c = AgentSkillCatalog()
    assert len(c.discover()) == 2
    activated = c.activate("COMPARE")
    assert activated.version == "0.11.4" and "references/comparison.md" in activated.resources
    assert "references/recommendation.md" not in activated.resources
    assert c.activate("PREPARE_PURCHASE").skill_id == "wealth-trade-assistance"
    with pytest.raises(ValueError):
        c.read("../wealth/needs.py")
    with pytest.raises(ValueError):
        c.activate("RECOMMEND", "$not-a-skill")
    link = Path(c.root / "outside.md")
    try:
        link.symlink_to(tmp_path / "outside.md")
        with pytest.raises(ValueError):
            c.read("outside.md")
    finally:
        link.unlink(missing_ok=True)


async def test_persisted_prepare_to_review_and_existing_draft_update(wealth, monkeypatch):
    from uuid import UUID

    from sqlalchemy import func, select
    from test_wealth_repairs import reassemble

    from banking_api.application.conversation_service import ConversationService
    from banking_api.domain.enums import RuntimeBackend
    from banking_api.llm.fake_provider import FakeLLMProvider
    from banking_api.persistence.models import OperationModel, TaskModel, WorkflowModel
    from banking_api.routing.request_router import RequestRouter

    await assessment(wealth)
    app, _ = reassemble(wealth, monkeypatch, True)
    factory, clock, *_ = wealth
    app.state.task_runner.router = RequestRouter(FakeLLMProvider([]))
    app.state.task_runner.wealth_clock = clock
    async with factory() as s:
        c = await ConversationService(
            s, app.state.task_runner.bus, runtime_backend=RuntimeBackend.LANGGRAPH
        ).create(user_id=USER, title="test stages")

    async def ask(text):
        async with factory() as s:
            accepted = await ConversationService(
                s, app.state.task_runner.bus, runtime_backend=RuntimeBackend.LANGGRAPH
            ).accept_message(conversation_id=c.conversation_id, user_id=USER, content=text)
        await app.state.task_runner.run(accepted.task_id)
        async with factory() as s:
            task = await s.get(TaskModel, accepted.task_id)
            assert task.status != "FAILED", task.error_json
            return task

    first = await ask("我预算5千，想要赚钱，可接受部分亏损，有什么适合我的产品吗")
    assert first.input_json["wealth_intent"]["source_text"].startswith("我预算5千")
    assert first.output_json["wealth_analysis"]["needs"]["amount"] == "5000"
    assert first.output_json["wealth_analysis"]["needs"]["return_goal"] == "GROWTH"
    prep = await ask("我要购买演示均衡优选")
    assert prep.output_json["wealth_analysis"]["result_kind"] == "PREPARE_PURCHASE"
    review = await ask("用工资卡，买三千元")
    async with factory() as s:
        wf = await s.get(WorkflowModel, UUID(review.output_json["workflow_id"]))
        assert wf.state_json["draft"]["quantity"] == "3000"
        assert wf.status == "READY_FOR_REVIEW"
        wid = str(wf.workflow_id)
    changed = await ask("用工资卡，买五千元")
    assert changed.output_json["workflow_id"] == wid
    assert changed.status == "COMPLETED"
    async with factory() as s:
        assert await s.scalar(select(func.count()).select_from(WorkflowModel)) == 1
        assert await s.scalar(select(func.count()).select_from(OperationModel)) == 0
        assert (await s.get(WorkflowModel, UUID(wid))).state_json["draft"]["quantity"] == "5000"


async def test_user_risk_cap_cannot_be_replaced_by_candidate_grade(wealth):
    await assessment(wealth)
    r = await result(wealth, "只看R2以下，预算五千元")
    skill = AgentSkillCatalog().activate("RECOMMEND")
    cid = r.candidates[0].fact_id
    bad = json.dumps(
        {
            "headline": "只看{{" + cid + ".risk}}及以下",
            "paragraphs": [],
            "questions": [],
            "relations": [],
        }
    )
    assert apply_answer(r, bad, skill).answer.generation_source == "DETERMINISTIC_FALLBACK"
    good = json.dumps(
        {
            "headline": "只看{{needs.maximum_risk}}及以下，费用与开放安排各有差异。",
            "paragraphs": [],
            "questions": [],
            "relations": [],
        }
    )
    out = apply_answer(r, good, skill)
    assert out.answer.generation_source == "MODEL_GENERATED"
    assert "R2" in out.answer.headline


async def test_next_week_uncertain_date_is_not_liquidity_match(wealth):
    await assessment(wealth)
    r = await result(wealth, "下周可能用到钱，预算五千，可以买周开放理财吗")
    assert r.needs.use_date_from and r.needs.use_date_to
    assert r.needs.use_date_from != r.needs.use_date_to
    assert r.status != "MATCHED"
    assert not r.candidates, "earliest possible use precedes the new-investment cash chain"


@pytest.mark.parametrize(
    "messages,assessed",
    [
        (
            ["有五千块，半年左右不用，想获得收益，亏一点可以接受", "先看看稳健一点的", "买第一款"],
            True,
        ),
        (["比较演示均衡优选和演示均衡周享", "投0.5万，费用差多少", "每天开放是不是马上拿钱"], True),
        (["不能亏本金", "改一下，我可以承担部分本金损失，最多10%"], True),
        (["推荐理财，预算五千元", "第一款适合买么", "如果买五千元，手续费多少"], True),
        (["什么是最大回撤", "推荐理财", "我要买演示稳享日日", "测评做完了"], False),
        (["最近有什么理财产品吗", "有什么适合我的理财产品推荐？", "我要买演示稳享日日"], False),
        (["比较演示均衡优选和演示均衡周享", "我就买这个"], True),
        (["推荐理财，预算五千元"], True),
    ],
)
async def test_continuous_readonly_and_prepare_scenarios(wealth, monkeypatch, messages, assessed):
    from sqlalchemy import func, select
    from test_wealth_repairs import reassemble

    from banking_api.application.conversation_service import ConversationService
    from banking_api.domain.enums import RuntimeBackend
    from banking_api.llm.fake_provider import FakeLLMProvider
    from banking_api.persistence.models import OperationModel, TaskModel, WorkflowModel
    from banking_api.routing.request_router import RequestRouter

    if assessed:
        await assessment(wealth)
    app, _ = reassemble(wealth, monkeypatch, True)
    factory, clock, *_ = wealth
    app.state.task_runner.router = RequestRouter(FakeLLMProvider([]))
    app.state.task_runner.wealth_clock = clock
    async with factory() as session:
        conversation = await ConversationService(
            session, app.state.task_runner.bus, runtime_backend=RuntimeBackend.LANGGRAPH
        ).create(user_id=USER, title="continuous")
    results = []
    for message in messages:
        async with factory() as session:
            accepted = await ConversationService(
                session, app.state.task_runner.bus, runtime_backend=RuntimeBackend.LANGGRAPH
            ).accept_message(
                conversation_id=conversation.conversation_id, user_id=USER, content=message
            )
        await app.state.task_runner.run(accepted.task_id)
        async with factory() as session:
            task = await session.get(TaskModel, accepted.task_id)
            assert task.status == "COMPLETED", task.error_json
            assert "wealth_analysis" in task.output_json, (message, task.output_json)
            results.append(task.output_json["wealth_analysis"])
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(OperationModel)) == 0
        assert await session.scalar(select(func.count()).select_from(WorkflowModel)) == 0
    if messages[0].startswith("有五千"):
        assert results[0]["needs"]["amount"] == "5000"
        assert results[-1]["result_kind"] == "PREPARE_PURCHASE"
        assert results[-1]["needs"]["constraints"]["preferred_risk"] == 2
    elif messages[0] == "不能亏本金":
        assert results[0]["status"] == "NO_MATCH"
        assert not results[-1]["needs"]["constraints"]["no_principal_loss"]
    elif not assessed:
        assert results[0]["status"] == "EDUCATION"
        assert all(r["status"] == "NEEDS_ASSESSMENT" for r in results[1:])
        if messages[0] == "最近有什么理财产品吗":
            assert len(results[0]["candidates"]) == 8
            assert not results[0]["answer"]["questions"]
            assert all(not c["product"]["purchase_allowed"] for c in results[0]["candidates"])
    elif messages[-1] == "我就买这个":
        assert results[-1]["status"] == "NEEDS_CLARIFICATION"
    elif messages[-1] == "每天开放是不是马上拿钱":
        assert results[1]["needs"]["amount"] == "5000.0"
        assert results[-1]["status"] == "EDUCATION"
    else:
        assert results[-1]["answer"]["generation_source"] == "DETERMINISTIC_FALLBACK"


async def test_hypothetical_fee_question_cannot_be_promoted_to_purchase():
    text = "如果买演示均衡优选五千元，手续费多少"
    frame = fallback_frame(text)
    frame.action = "PREPARE_PURCHASE"
    provider = FakeLLMProvider([LLMResponse(content=json.dumps(frame.model_dump(mode="json")))])
    verified = await interpret(provider, text)
    assert verified.action == "COMPARE"
    assert verified.quantity_mentions[0].value == "5000"


async def test_chinese_literal_financial_number_needs_typed_fact(wealth):
    await assessment(wealth)
    r = await result(wealth, "预算五千，推荐理财")
    payload = {"headline": "费用为二万元", "paragraphs": [], "questions": [], "relations": []}
    out = apply_answer(r, json.dumps(payload), AgentSkillCatalog().activate("RECOMMEND"))
    assert out.answer.generation_source == "DETERMINISTIC_FALLBACK"
    assert "二万元" not in out.answer.headline
