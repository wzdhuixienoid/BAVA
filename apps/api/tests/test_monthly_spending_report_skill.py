import json
from decimal import Decimal
from pathlib import Path

import pytest

from banking_api.financial.analysis_snapshot import (
    FinancialAnalysisSnapshot,
    ToolEvidence,
)
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.financial.models import (
    CategoryBreakdown,
    SpendingPeriodComparison,
    SpendingSummary,
    TopTransactions,
)
from banking_api.financial.report_formatter import ReportFormatter
from banking_api.financial.report_models import DataQualityStatus
from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.llm.models import LLMResponse, LLMToolCall
from banking_api.llm.provider import LLMProviderError
from banking_api.main import create_app
from banking_api.mock_bank.service import MockBankService
from banking_api.registries.skill_registry import SkillRegistry
from banking_api.skill_runtime.executor import (
    SkillErrorCode,
    SkillExecutionError,
    SkillExecutor,
)
from banking_api.skills.monthly_spending_report import MonthlySpendingReportSkill

DATA_DIR = Path(__file__).parents[1] / "src/banking_api/mock_bank/data"


def valid_narrative() -> LLMResponse:
    return LLMResponse(
        content=json.dumps(
            {
                "headline": "本月支出上升且结构集中",
                "insights": [
                    {
                        "type": "STRUCTURE",
                        "title": "住房是最主要的支出类别",
                        "narrative": "消费结构主要由住房、购物和旅行构成。",
                        "evidence_refs": [
                            "category_breakdown.HOUSING.share",
                            "category_breakdown.SHOPPING.share",
                            "category_breakdown.TRAVEL.share",
                        ],
                    },
                    {
                        "type": "CHANGE",
                        "title": "旅行和购物是主要增量来源",
                        "narrative": "本月支出明显上升，旅行和购物的变化最突出。",
                        "evidence_refs": [
                            "period_comparison.absolute_change",
                            "category_breakdown.TRAVEL.absolute_change",
                            "category_breakdown.SHOPPING.absolute_change",
                        ],
                    },
                ],
            },
            ensure_ascii=False,
        )
    )


def partial_narrative() -> LLMResponse:
    return LLMResponse(
        content=json.dumps(
            {
                "headline": "本月消费结构集中",
                "insights": [
                    {
                        "type": "STRUCTURE",
                        "title": "住房是主要支出类别",
                        "narrative": "住房在当前消费结构中最为突出。",
                        "evidence_refs": ["category_breakdown.HOUSING.share"],
                    },
                    {
                        "type": "DATA_QUALITY",
                        "title": "报告数据范围有限",
                        "narrative": "当前证据足以展示消费结构，但不包含全部报告章节。",
                        "evidence_refs": ["data_quality.status"],
                    },
                ],
            },
            ensure_ascii=False,
        )
    )


def account_narrative() -> LLMResponse:
    return LLMResponse(
        content=json.dumps(
            {
                "headline": "本月工资卡消费结构集中",
                "insights": [
                    {
                        "type": "STRUCTURE",
                        "title": "住房是主要支出类别",
                        "narrative": "住房在工资卡的消费结构中最为突出。",
                        "evidence_refs": ["category_breakdown.HOUSING.share"],
                    },
                    {
                        "type": "CHANGE",
                        "title": "餐饮变化值得关注",
                        "narrative": "餐饮是工资卡消费变化中较为突出的类别。",
                        "evidence_refs": ["category_breakdown.FOOD.absolute_change"],
                    },
                ],
            },
            ensure_ascii=False,
        )
    )


def golden_snapshot() -> FinancialAnalysisSnapshot:
    golden = json.loads((DATA_DIR / "golden_financial_metrics.json").read_text(encoding="utf-8"))
    august = golden["months"]["2026-08"]
    comparison = golden["comparisons"]["2026-07_to_2026-08"]
    return FinancialAnalysisSnapshot(
        period="2026-08",
        account_ids=[],
        spending_summary=SpendingSummary.model_validate(august["summary"]),
        category_breakdown=CategoryBreakdown.model_validate(august["category_breakdown"]),
        period_comparison=SpendingPeriodComparison.model_validate(comparison),
        top_transactions=TopTransactions.model_validate(august["top_transactions"]),
        tool_evidence=[
            ToolEvidence(
                capability_id="transaction.spending_summary",
                input={"month": "2026-08"},
            ),
            ToolEvidence(
                capability_id="transaction.category_breakdown",
                input={"month": "2026-08"},
            ),
            ToolEvidence(
                capability_id="transaction.compare_periods",
                input={"month": "2026-08"},
            ),
            ToolEvidence(
                capability_id="transaction.top_transactions",
                input={"month": "2026-08", "limit": 5},
            ),
        ],
    )


def account_snapshot() -> FinancialAnalysisSnapshot:
    analytics = FinancialAnalyticsService(MockBankService())
    account_ids = ["acc_salary"]
    return FinancialAnalysisSnapshot(
        period="2026-08",
        account_ids=account_ids,
        spending_summary=analytics.spending_summary("2026-08", account_ids, user_id="dev-user-001"),
        category_breakdown=analytics.category_breakdown(
            "2026-08", account_ids, user_id="dev-user-001"
        ),
        period_comparison=analytics.compare_periods("2026-08", account_ids, user_id="dev-user-001"),
        top_transactions=analytics.top_transactions(
            "2026-08", 5, account_ids, user_id="dev-user-001"
        ),
        tool_evidence=[
            ToolEvidence(capability_id="account.list", input={}),
            ToolEvidence(
                capability_id="transaction.spending_summary",
                input={"month": "2026-08", "account_ids": account_ids},
            ),
            ToolEvidence(
                capability_id="transaction.category_breakdown",
                input={"month": "2026-08", "account_ids": account_ids},
            ),
            ToolEvidence(
                capability_id="transaction.compare_periods",
                input={"month": "2026-08", "account_ids": account_ids},
            ),
            ToolEvidence(
                capability_id="transaction.top_transactions",
                input={"month": "2026-08", "limit": 5, "account_ids": account_ids},
            ),
        ],
    )


async def test_complete_snapshot_generates_structured_report_without_tools() -> None:
    provider = FakeLLMProvider([valid_narrative()])

    report = await SkillExecutor(provider).execute(golden_snapshot())

    assert report.report_version == 1
    assert report.period == "2026-08"
    assert report.overview.total_spending_display == "¥16,547.30"
    assert report.period_comparison is not None
    assert report.period_comparison.percentage_change_display == "+77.3%"
    assert report.data_quality.status is DataQualityStatus.COMPLETE
    assert len(report.insights) == 2
    assert provider.requests[0].tools == []


async def test_account_specific_snapshot_preserves_scope() -> None:
    provider = FakeLLMProvider([account_narrative()])

    report = await SkillExecutor(provider).execute(account_snapshot())

    assert report.scope.account_ids == ["acc_salary"]
    assert report.overview.total_spending == Decimal("7657.30")
    assert report.overview.total_spending_display == "¥7,657.30"
    assert all(item.account_id == "acc_salary" for item in report.top_transactions)


def test_report_formatter_is_deterministic() -> None:
    formatter = ReportFormatter()

    assert formatter.money(Decimal("16547.30"), "CNY") == "¥16,547.30"
    assert formatter.money_change(Decimal("7214.10"), "CNY") == "+¥7,214.10"
    assert formatter.money_change(Decimal("-320"), "CNY") == "-¥320.00"
    assert formatter.percentage_change(Decimal("77.295032")) == "+77.3%"
    assert formatter.percentage_change(Decimal("-12.34")) == "-12.3%"
    assert formatter.percentage_change(Decimal("-0.01")) == "0.0%"
    assert formatter.percentage_change(None) == "—"
    assert formatter.ratio(Decimal("0.374683")) == "37.5%"


async def test_category_order_and_top_n_are_preserved() -> None:
    snapshot = golden_snapshot()
    report = await SkillExecutor(FakeLLMProvider([valid_narrative()])).execute(snapshot)

    assert [item.category for item in report.category_breakdown] == [
        item.category
        for item in snapshot.category_breakdown.categories  # type: ignore[union-attr]
    ]
    assert [item.transaction_id for item in report.top_transactions] == [
        item.transaction_id
        for item in snapshot.top_transactions.transactions  # type: ignore[union-attr]
    ]


async def test_incomplete_input_fails_without_llm_call() -> None:
    snapshot = golden_snapshot().model_copy(update={"category_breakdown": None})
    provider = FakeLLMProvider([])

    with pytest.raises(SkillExecutionError) as captured:
        await SkillExecutor(provider).execute(snapshot)

    assert captured.value.code is SkillErrorCode.REPORT_INPUT_INCOMPLETE
    assert provider.requests == []


async def test_non_snapshot_input_is_rejected() -> None:
    provider = FakeLLMProvider([])

    with pytest.raises(SkillExecutionError) as captured:
        await SkillExecutor(provider).execute({"period": "2026-08"})  # type: ignore[arg-type]

    assert captured.value.code is SkillErrorCode.REPORT_INPUT_INCOMPLETE
    assert provider.requests == []


async def test_partial_report_marks_missing_optional_sections() -> None:
    snapshot = golden_snapshot().model_copy(
        update={"period_comparison": None, "top_transactions": None}
    )

    report = await SkillExecutor(FakeLLMProvider([partial_narrative()])).execute(snapshot)

    assert report.data_quality.status is DataQualityStatus.PARTIAL
    assert len(report.data_quality.notes) == 2
    assert report.period_comparison is None
    assert report.top_transactions == []


@pytest.mark.parametrize(
    "response",
    [
        LLMResponse(
            content=(
                '{"headline":"本月消费结构集中","insights":['
                '{"type":"STRUCTURE","title":"住房突出","narrative":"住房是主要支出。",'
                '"evidence_refs":["category_breakdown.UNKNOWN.amount"]},'
                '{"type":"CHANGE","title":"支出上升","narrative":"整体支出上升。",'
                '"evidence_refs":["period_comparison.absolute_change"]}]}'
            )
        ),
        LLMResponse(
            content=(
                '{"headline":"本月支出增长77.3%","insights":['
                '{"type":"STRUCTURE","title":"住房突出","narrative":"住房是主要支出。",'
                '"evidence_refs":["category_breakdown.HOUSING.share"]},'
                '{"type":"CHANGE","title":"支出上升","narrative":"整体支出上升。",'
                '"evidence_refs":["period_comparison.absolute_change"]}]}'
            )
        ),
        LLMResponse(
            content=(
                '{"headline":"本月支出上升","insights":['
                '{"type":"STRUCTURE","title":"未知类别","narrative":"INSURANCE 成为主要支出。",'
                '"evidence_refs":["overview.total_spending"]},'
                '{"type":"CHANGE","title":"支出上升","narrative":"整体支出上升。",'
                '"evidence_refs":["period_comparison.absolute_change"]}]}'
            )
        ),
        LLMResponse(
            content=(
                '{"headline":"本月支出上升","insights":['
                '{"type":"STRUCTURE","title":"未知账户","narrative":"acc_unknown 是主要支出账户。",'
                '"evidence_refs":["overview.total_spending"]},'
                '{"type":"CHANGE","title":"支出上升","narrative":"整体支出上升。",'
                '"evidence_refs":["period_comparison.absolute_change"]}]}'
            )
        ),
    ],
)
async def test_invalid_narrative_fails_after_one_retry(response: LLMResponse) -> None:
    provider = FakeLLMProvider([response, response])

    with pytest.raises(SkillExecutionError) as captured:
        await SkillExecutor(provider).execute(golden_snapshot())

    assert captured.value.code is SkillErrorCode.REPORT_NARRATIVE_VALIDATION_FAILED
    assert len(provider.requests) == 2


async def test_malformed_json_is_corrected_once() -> None:
    provider = FakeLLMProvider([LLMResponse(content="not-json"), valid_narrative()])

    report = await SkillExecutor(provider).execute(golden_snapshot())

    assert report.headline
    assert len(provider.requests) == 2
    assert all(request.tools == [] for request in provider.requests)


async def test_unexpected_tool_call_fails_immediately() -> None:
    provider = FakeLLMProvider(
        [
            LLMResponse(
                tool_calls=[
                    LLMToolCall(
                        id="forbidden",
                        name="get_spending_summary",
                        arguments={"month": "2026-08"},
                    )
                ]
            )
        ]
    )

    with pytest.raises(SkillExecutionError) as captured:
        await SkillExecutor(provider).execute(golden_snapshot())

    assert captured.value.code is SkillErrorCode.SKILL_UNEXPECTED_TOOL_CALL
    assert len(provider.requests) == 1


async def test_provider_failure_is_structured() -> None:
    provider = FakeLLMProvider([LLMProviderError("offline", retryable=True)])

    with pytest.raises(SkillExecutionError) as captured:
        await SkillExecutor(provider).execute(golden_snapshot())

    assert captured.value.code is SkillErrorCode.SKILL_LLM_PROVIDER_ERROR


def test_skill_registry_contains_only_monthly_report_skill() -> None:
    registry = SkillRegistry()
    registry.register(MonthlySpendingReportSkill.definition)

    skill = registry.get("skill:monthly-spending-report")
    assert skill is not None
    assert skill.version == 1
    assert skill.input_schema is FinancialAnalysisSnapshot
    assert skill.allowed_tools == ()
    assert registry.all() == (skill,)


def test_application_registers_monthly_report_skill() -> None:
    skills = create_app().state.skill_registry

    assert [skill.skill_id for skill in skills.all()] == [
        "skill:monthly-spending-report",
        "skill:wealth-recommendation",
    ]
    wealth = skills.get("skill:wealth-recommendation")
    assert wealth.allowed_tools == ()
    assert wealth.input_schema.__name__ == "WealthAnalysis"
    assert skills.all()[0].allowed_tools == ()
