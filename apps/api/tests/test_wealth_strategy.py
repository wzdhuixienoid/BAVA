"""User-feedback regressions: strategy-aware recommendations, alternatives and positioning."""

import json
from datetime import datetime

import pytest
from test_wealth import USER, assessment
from test_wealth import wealth as wealth

from banking_api.agent_skills import AgentSkillCatalog
from banking_api.knowledge.wealth import KeywordWealthKnowledge, safe_source
from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.llm.models import LLMResponse
from banking_api.wealth.advisory import WealthAdvisoryService
from banking_api.wealth.answer import apply_answer, fact_pack
from banking_api.wealth.calculation import CN
from banking_api.wealth.catalog import seed_catalog
from banking_api.wealth.coordination import analysis_request
from banking_api.wealth.semantic import fallback_frame, interpret
from banking_api.wealth.service import WealthService


async def analyze(wealth, text, previous=None):
    factory, clock, balances, *_ = wealth
    clock.now = datetime(2026, 10, 12, 10, tzinfo=CN)
    async with factory() as session:
        service = WealthService(session, balances, clock)
        frame = fallback_frame(text, previous)
        body = analysis_request(frame, await service.products(USER), previous)
        return await WealthAdvisoryService(service).analyze(USER, body, previous)


async def test_growth_goal_changes_strategy_candidates_without_inventing_risk_grade(wealth):
    await assessment(wealth)
    conservative = await analyze(wealth, "预算5000元，推荐理财")
    growth = await analyze(wealth, "我预算5千，想要赚钱，可接受部分亏损，有什么适合我的产品吗")
    assert growth.needs.amount == "5000"
    assert growth.needs.constraints.preferred_risk is None
    assert [c.product.product_id for c in growth.candidates] != [
        c.product.product_id for c in conservative.candidates
    ]
    assert growth.candidates[0].product.design_profile.growth_exposure > 0
    assert len({c.product.design_profile.growth_exposure for c in growth.candidates}) >= 2
    assert growth.recommendation_basis


async def test_rejecting_prior_returns_finds_new_choices_and_keeps_constraints(wealth):
    await assessment(wealth)
    first = await analyze(wealth, "预算5千，想要赚钱，可接受部分亏损，推荐理财")
    second = await analyze(wealth, "还有其他产品推荐吗，这些产品的收益太低了", first)
    assert second.needs.amount == "5000"
    assert second.needs.return_goal == "HIGHER_POTENTIAL"
    assert second.needs.seek_alternatives and not second.needs.constraints.ambiguous
    assert second.status == "CONDITIONAL" and second.candidates
    assert not set(c.product.product_id for c in first.candidates).intersection(
        c.product.product_id for c in second.candidates
    )
    assert second.candidates[0].product.design_profile.growth_exposure >= 60


@pytest.mark.parametrize(
    "text", ["你对每个产品的定位是什么？", "每款的策略和收益来源是什么", "介绍各个产品的投资方向"]
)
async def test_positioning_question_is_objective_even_after_an_unmatched_request(wealth, text):
    await assessment(wealth)
    unmatched = await analyze(wealth, "必须保本")
    assert unmatched.status == "NO_MATCH"
    overview = await analyze(wealth, text, unmatched)
    assert overview.result_kind == "PRODUCT_OVERVIEW" and overview.status == "EDUCATION"
    assert len(overview.candidates) == 8 and not overview.customer_response.questions
    assert all(c.product.design_profile for c in overview.candidates)
    assert any(e.scope == "DESIGN" for e in overview.evidence)
    assert all(not c.product.purchase_allowed for c in overview.candidates)


async def test_design_overview_does_not_require_assessment_and_does_not_grant_purchase(wealth):
    overview = await analyze(wealth, "每个产品的定位是什么")
    assert overview.status == "EDUCATION" and len(overview.candidates) == 8
    assert all(not c.product.purchase_allowed for c in overview.candidates)


@pytest.mark.parametrize(
    "text",
    [
        "最近有什么理财产品吗",
        "现在有哪些理财产品？",
        "看看理财产品列表",
        "有哪些在售产品",
    ],
)
async def test_unassessed_catalogue_is_visible_even_if_model_calls_it_recommendation(wealth, text):
    frame = await interpret(
        FakeLLMProvider(
            [
                LLMResponse(
                    content=json.dumps(
                        {
                            "action": "RECOMMEND",
                            "product_mentions": ["理财产品"] if "理财产品" in text else [],
                            "ambiguities": ["未完成风险测评"],
                            "clarification": ["这次计划投资多少元？"],
                        }
                    )
                )
            ]
        ),
        text,
    )
    assert frame.action == "CATALOGUE" and not frame.ambiguities
    factory, clock, balances, *_ = wealth
    async with factory() as session:
        svc = WealthService(session, balances, clock)
        result = await WealthAdvisoryService(svc).analyze(
            USER, analysis_request(frame, await svc.products(USER))
        )
    assert result.result_kind == "CATALOGUE" and result.status == "EDUCATION"
    assert len(result.candidates) == 8 and not result.customer_response.questions
    assert all(not c.product.purchase_allowed for c in result.candidates)
    assert not any(k.startswith("needs.") for k in fact_pack(result)[0])


@pytest.mark.parametrize(
    "recommendation_text",
    [
        "有什么适合我的理财产品推荐？",
        "有哪些适合我的理财产品？",
    ],
)
async def test_catalogue_does_not_unlock_unassessed_recommendation_or_purchase(
    wealth, recommendation_text
):
    catalogue = await analyze(wealth, "最近有什么理财产品吗")
    recommendation = await analyze(wealth, recommendation_text, catalogue)
    assert recommendation.status == "NEEDS_ASSESSMENT" and not recommendation.candidates
    purchase = await analyze(wealth, "我要买演示稳享日日", catalogue)
    assert purchase.status == "NEEDS_ASSESSMENT"
    assert all(not c.product.purchase_allowed for c in purchase.candidates)


async def test_catalogue_generated_answer_cannot_request_investment_conditions(wealth):
    result = await analyze(wealth, "最近有什么理财产品吗")
    checked = apply_answer(
        result,
        json.dumps(
            {
                "headline": "目前可以查看模拟产品。",
                "paragraphs": [],
                "questions": ["投资预算是多少元？"],
                "relations": [],
            }
        ),
        AgentSkillCatalog().activate("CATALOGUE"),
    )
    assert checked.narrative_source == "DETERMINISTIC_FALLBACK"
    assert len(checked.candidates) == 8 and not checked.answer.questions


async def test_growth_does_not_relax_explicit_risk_cap_or_principal_requirements(wealth):
    await assessment(wealth)
    first = await analyze(wealth, "预算5000元，只看R2以下，想要赚钱")
    other = await analyze(wealth, "还有其他推荐吗，收益太低了", first)
    assert other.needs.constraints.maximum_risk == 2
    assert all(int(c.product.risk[1]) <= 2 for c in other.candidates)
    guaranteed = await analyze(wealth, "预算5000元，必须保本，想要赚钱")
    assert not guaranteed.candidates and guaranteed.status == "NO_MATCH"


async def test_compare_has_strategy_risks_and_checked_exposure_relations(wealth):
    await assessment(wealth)
    comparison = await analyze(wealth, "比较演示进取成长和演示高波动精选，预算5000元")
    facts, relations = fact_pack(comparison)
    first, second = comparison.candidates
    assert (
        first.product.design_profile.growth_exposure < second.product.design_profile.growth_exposure
    )
    assert any(r["kind"] == "HIGHER_CONCENTRATION" for r in relations.values())
    assert any(r["kind"] == "MORE_GROWTH_EXPOSURE" for r in relations.values())
    assert "主题" in facts[f"{second.fact_id}.risk_drivers"]
    assert all(c.product.design_profile.scenarios for c in comparison.candidates)


async def test_grade_and_fee_only_generated_answer_is_rejected_when_design_is_available(wealth):
    await assessment(wealth)
    comparison = await analyze(wealth, "比较演示进取成长和演示高波动精选")
    c = comparison.candidates[0]
    superficial = json.dumps(
        {
            "headline": "可以比较风险和费用。",
            "paragraphs": [
                {
                    "block_id": "p",
                    "title": "对比",
                    "text": "风险为{{" + c.fact_id + ".risk}}。",
                    "fact_ids": [c.fact_id],
                }
            ],
            "questions": [],
            "relations": [],
        },
        ensure_ascii=False,
    )
    result = apply_answer(comparison, superficial, AgentSkillCatalog().activate("COMPARE"))
    assert result.narrative_source == "DETERMINISTIC_FALLBACK"
    assert "strategy" in result.validation_error


async def test_design_is_new_immutable_evidence_not_a_rewrite_of_old_contracts(wealth):
    factory, clock, balances, *_ = wealth
    async with factory() as session:
        svc = WealthService(session, balances, clock)
        old = await svc.version("mock-wealth-04")
        before = old.content_hash, dict(old.terms)
        assert (await svc.product("mock-wealth-04")).design_profile is None
        clock.now = datetime(2026, 10, 12, 10, tzinfo=CN)
        product = await svc.product("mock-wealth-04")
        assert sum(product.design_profile.allocation.values()) == 100
        assert "并非" in product.design_profile.notice
        await seed_catalog(session)
        assert (old.content_hash, old.terms) == before
        retriever = KeywordWealthKnowledge(svc)
        current = await retriever.fragments("产品定位与策略", product.product_id)
        historical = await retriever.fragments(
            "产品定位与策略", product.product_id, product.version_id
        )
        assert any(e.scope == "DESIGN" and safe_source(e.url, e.scope) for e in current)
        assert not any(e.scope == "DESIGN" for e in historical)


async def test_missing_preference_is_not_a_hard_conflict_but_real_conflicts_remain():
    raw = {"action": "RECOMMEND", "ambiguities": ["没有具体风险等级和用款期限"]}
    frame = await interpret(FakeLLMProvider([LLMResponse(content=json.dumps(raw))]), "想要更多收益")
    assert not frame.ambiguities
    raw["ambiguities"] = ["用户提出了互相矛盾的本金要求"]
    frame = await interpret(FakeLLMProvider([LLMResponse(content=json.dumps(raw))]), "想要更多收益")
    assert frame.ambiguities


async def test_plural_product_feedback_is_not_a_single_selection_requirement(wealth):
    await assessment(wealth)
    first = await analyze(wealth, "预算5千，想要赚钱，推荐理财")
    text = "还有其他产品推荐吗，这些产品的收益太低了"
    frame = await interpret(
        FakeLLMProvider(
            [LLMResponse(content=json.dumps({"action": "RECOMMEND", "references": ["这些产品"]}))]
        ),
        text,
        first,
    )
    factory, clock, balances, *_ = wealth
    async with factory() as session:
        svc = WealthService(session, balances, clock)
        body = analysis_request(frame, await svc.products(USER), first)
        second = await WealthAdvisoryService(svc).analyze(USER, body, first)
    assert not frame.ambiguities
    assert second.candidates and second.needs.amount == "5000"


async def test_unavailable_model_can_still_recognize_an_objective_positioning_question():
    frame = await interpret(FakeLLMProvider([]), "你对每个产品的定位是什么？")
    assert frame.action == "PRODUCT_OVERVIEW" and not frame.ambiguities


@pytest.mark.parametrize(
    "text",
    [
        "比较这两个产品的策略和收益来源",
        "对比演示均衡优选和演示进取成长这两个产品的定位",
    ],
)
async def test_explicit_strategy_comparison_is_not_replaced_by_a_catalogue_overview(text):
    frame = await interpret(FakeLLMProvider([]), text)
    assert frame.action == "COMPARE"


async def test_preference_update_does_not_reuse_a_prior_explanation_snapshot(wealth):
    await assessment(wealth)
    previous = await analyze(wealth, "预算5000元，想要赚钱，推荐理财")
    updated = await analyze(wealth, "我不要这么大的波动，只看R2以下，有什么适合我的？", previous)
    assert updated.result_kind == "RECOMMENDATION"
    assert updated.needs.constraints.maximum_risk == 2
    assert all(int(c.product.risk[1]) <= 2 for c in updated.candidates)


async def test_verified_relation_object_and_negative_forecast_can_be_rendered(wealth):
    await assessment(wealth)
    comparison = await analyze(wealth, "比较演示进取成长和演示高波动精选")
    c = comparison.candidates[0]
    _, relations = fact_pack(comparison)
    reference = next(k for k, value in relations.items() if value["kind"] == "LOWER_RISK")
    payload = {
        "headline": "比较分散成长与主题集中策略。",
        "paragraphs": [
            {
                "block_id": "strategy",
                "title": "收益来源与代价",
                "text": "{{"
                + c.fact_id
                + ".positioning}}；风险是{{"
                + c.fact_id
                + ".risk_drivers}}。费率较低不等于未来收益更高。",
                "fact_ids": [c.fact_id],
                "evidence_ids": c.evidence_ids,
            }
        ],
        "questions": [],
        "relations": [{"id": reference, "kind": "LOWER_RISK"}],
    }
    result = apply_answer(comparison, json.dumps(payload), AgentSkillCatalog().activate("COMPARE"))
    assert result.narrative_source == "MODEL_GENERATED", result.validation_error
    payload["relations"][0]["kind"] = "HIGHER_CONCENTRATION"
    result = apply_answer(comparison, json.dumps(payload), AgentSkillCatalog().activate("COMPARE"))
    assert result.narrative_source == "DETERMINISTIC_FALLBACK"


async def test_previous_strategy_context_is_saved_and_overview_excludes_investment_fields(wealth):
    await assessment(wealth)
    first = await analyze(wealth, "预算5000元，想要赚钱，推荐理财")
    second = await analyze(wealth, "还有其他推荐吗，收益太低了", first)
    assert [p.name for p in second.previous_product_context] == [
        c.product.name for c in first.candidates
    ]
    assert any("分散权益" in p.strategy for p in second.previous_product_context)
    overview = await analyze(wealth, "每个产品的定位是什么", second)
    facts, _ = fact_pack(overview)
    assert not any(k.startswith("needs.") for k in facts)


async def test_asset_allocation_cannot_prove_dividend_income_proportions(wealth):
    await assessment(wealth)
    result = await analyze(wealth, "比较演示进取成长和演示高波动精选")
    c = result.candidates[1]
    payload = {
        "headline": "比较策略和代价。",
        "paragraphs": [
            {
                "block_id": "income",
                "title": "增长来源",
                "text": "{{"
                + c.fact_id
                + ".positioning}}，风险是{{"
                + c.fact_id
                + ".risk_drivers}}。分红与票息只占少量。",
                "fact_ids": [c.fact_id],
                "evidence_ids": c.evidence_ids,
            }
        ],
        "questions": [],
        "relations": [],
    }
    checked = apply_answer(result, json.dumps(payload), AgentSkillCatalog().activate("COMPARE"))
    assert checked.narrative_source == "DETERMINISTIC_FALLBACK"
    assert "income contribution" in checked.validation_error


async def test_strategy_dialogue_runs_as_owned_persistent_tasks_without_financial_writes(
    wealth, monkeypatch
):
    from sqlalchemy import func, select
    from test_wealth_repairs import reassemble

    from banking_api.application.conversation_service import ConversationService
    from banking_api.domain.enums import RuntimeBackend
    from banking_api.persistence.models import OperationModel, TaskModel, WorkflowModel
    from banking_api.routing.request_router import RequestRouter

    await assessment(wealth)
    app, _ = reassemble(wealth, monkeypatch, True)
    factory, clock, *_ = wealth
    clock.now = datetime(2026, 10, 12, 10, tzinfo=CN)
    app.state.task_runner.router = RequestRouter(FakeLLMProvider([]))
    app.state.task_runner.wealth_clock = clock
    async with factory() as session:
        conversation = await ConversationService(
            session, app.state.task_runner.bus, runtime_backend=RuntimeBackend.LANGGRAPH
        ).create(user_id=USER, title="strategy feedback")
    results = []
    for message in [
        "我预算5千，想要赚钱，可接受部分亏损，有什么适合我的产品吗",
        "还有其他产品推荐吗，这些产品的收益太低了",
        "你对每个产品的定位是什么？",
        "我不要这么大的波动，只看R2以下，有什么适合我的？",
    ]:
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
            results.append(task.output_json["wealth_analysis"])
    assert results[0]["candidates"][0]["product"]["risk"] == "R3"
    assert results[1]["needs"]["seek_alternatives"] and results[1]["candidates"]
    assert results[2]["result_kind"] == "PRODUCT_OVERVIEW"
    assert len(results[2]["candidates"]) == 8 and not results[2]["answer"]["questions"]
    assert all(int(c["product"]["risk"][1]) <= 2 for c in results[3]["candidates"])
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(OperationModel)) == 0
        assert await session.scalar(select(func.count()).select_from(WorkflowModel)) == 0
