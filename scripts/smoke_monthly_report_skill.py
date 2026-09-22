"""Opt-in real-provider smoke for MonthlySpendingReportSkill."""

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from banking_api.config.settings import Settings
from banking_api.financial.analysis_snapshot import (
    FinancialAnalysisSnapshot,
    ToolEvidence,
)
from banking_api.financial.models import (
    CategoryBreakdown,
    SpendingPeriodComparison,
    SpendingSummary,
    TopTransactions,
)
from banking_api.financial.report_models import MonthlySpendingReportCore
from banking_api.llm.models import LLMRequest, LLMResponse
from banking_api.llm.openai_compatible_provider import OpenAICompatibleProvider
from banking_api.skill_runtime.executor import SkillExecutor
from banking_api.skills.monthly_spending_report import MonthlySpendingReportSkill

DATA_DIR = (
    Path(__file__).parents[1]
    / "apps"
    / "api"
    / "src"
    / "banking_api"
    / "mock_bank"
    / "data"
)


class RecordingProvider:
    def __init__(self, provider: OpenAICompatibleProvider) -> None:
        self.provider = provider
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request.model_copy(deep=True))
        return await self.provider.generate(request)


def build_snapshot(metrics: dict[str, Any]) -> FinancialAnalysisSnapshot:
    august = metrics["months"]["2026-08"]
    return FinancialAnalysisSnapshot(
        period="2026-08",
        account_ids=[],
        spending_summary=SpendingSummary.model_validate(august["summary"]),
        category_breakdown=CategoryBreakdown.model_validate(
            august["category_breakdown"]
        ),
        period_comparison=SpendingPeriodComparison.model_validate(
            metrics["comparisons"]["2026-07_to_2026-08"]
        ),
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


async def main() -> None:
    settings = Settings()
    if not settings.llm_base_url or not settings.llm_api_key or not settings.llm_model:
        raise SystemExit("LLM_BASE_URL, LLM_API_KEY and LLM_MODEL are required")
    print(
        "provider.config",
        {
            "provider": settings.llm_provider,
            "base_url_domain": urlparse(settings.llm_base_url).netloc,
            "model": settings.llm_model,
        },
    )
    metrics = json.loads(
        (DATA_DIR / "golden_financial_metrics.json").read_text(encoding="utf-8")
    )
    golden_core = json.loads(
        (DATA_DIR / "golden_monthly_report_core.json").read_text(encoding="utf-8")
    )["report_core"]
    snapshot = build_snapshot(metrics)
    skill = MonthlySpendingReportSkill()
    actual_core = skill.build_core(snapshot).model_dump(mode="json")
    if actual_core != golden_core:
        raise RuntimeError("Deterministic report core does not match Golden fixture")

    provider = RecordingProvider(
        OpenAICompatibleProvider(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    )
    report = await SkillExecutor(provider, skill=skill).execute(snapshot)
    if not provider.requests or any(request.tools for request in provider.requests):
        raise RuntimeError("Skill attempted to expose tools")
    if not report.headline or not 2 <= len(report.insights) <= 5:
        raise RuntimeError("Narrative shape is invalid")
    final_core = MonthlySpendingReportCore.model_validate(
        {
            key: value
            for key, value in report.model_dump(mode="json").items()
            if key not in {"headline", "insights"}
        }
    ).model_dump(mode="json")
    if final_core != golden_core:
        raise RuntimeError("Narrative execution changed deterministic numeric fields")

    print("skill.selected", MonthlySpendingReportSkill.definition.skill_id)
    print(
        "report.core",
        {
            "period": report.period,
            "total_spending": str(report.overview.total_spending),
            "total_spending_display": report.overview.total_spending_display,
            "percentage_change_display": (
                report.period_comparison.percentage_change_display
                if report.period_comparison is not None
                else None
            ),
            "category_count": len(report.category_breakdown),
            "top_transaction_count": len(report.top_transactions),
            "data_quality": report.data_quality.status.value,
        },
    )
    print("narrative.headline", report.headline)
    for insight in report.insights:
        print(
            "narrative.insight",
            {
                "type": insight.type.value,
                "title": insight.title,
                "narrative": insight.narrative,
                "evidence_refs": insight.evidence_refs,
            },
        )
    print(
        "validation",
        {
            "golden_core_equal": True,
            "tool_calls": 0,
            "insight_count": len(report.insights),
        },
    )


if __name__ == "__main__":
    asyncio.run(main())
