import json
import re
from enum import StrEnum
from typing import Any

from pydantic import ValidationError

from banking_api.financial.analysis_snapshot import FinancialAnalysisSnapshot
from banking_api.financial.report_models import (
    MonthlySpendingReport,
    MonthlySpendingReportCore,
    ReportNarrativeDraft,
)
from banking_api.llm.models import LLMMessage, LLMRequest
from banking_api.llm.provider import LLMProvider, LLMProviderError
from banking_api.skills.models import SkillDefinition
from banking_api.skills.monthly_spending_report import (
    MONTHLY_SPENDING_REPORT_INSTRUCTIONS,
    MonthlySpendingReportSkill,
    ReportInputError,
)

_NUMERIC_TEXT = re.compile(r"[0-9０-９零〇一二三四五六七八九十百千万亿两]")
_ENGLISH_NUMERIC_TEXT = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"first|second|third|fourth|fifth|hundred|thousand|million|billion)\b",
    re.IGNORECASE,
)
_CATEGORY_TOKEN = re.compile(r"\b[A-Z][A-Z_]{2,}\b")
_ACCOUNT_TOKEN = re.compile(r"\bacc_[A-Za-z0-9_-]+\b")


class SkillErrorCode(StrEnum):
    REPORT_INPUT_INCOMPLETE = "REPORT_INPUT_INCOMPLETE"
    SKILL_UNEXPECTED_TOOL_CALL = "SKILL_UNEXPECTED_TOOL_CALL"
    REPORT_NARRATIVE_VALIDATION_FAILED = "REPORT_NARRATIVE_VALIDATION_FAILED"
    SKILL_LLM_PROVIDER_ERROR = "SKILL_LLM_PROVIDER_ERROR"


class SkillExecutionError(Exception):
    def __init__(self, code: SkillErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class SkillExecutor:
    """Executes only the monthly report method; it is not a workflow engine."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        skill: MonthlySpendingReportSkill | None = None,
        max_retries: int = 1,
    ) -> None:
        self.provider = provider
        self.skill = skill or MonthlySpendingReportSkill()
        self.max_retries = max_retries

    async def execute(
        self, snapshot: FinancialAnalysisSnapshot
    ) -> MonthlySpendingReport:
        if not isinstance(snapshot, FinancialAnalysisSnapshot):
            raise SkillExecutionError(
                SkillErrorCode.REPORT_INPUT_INCOMPLETE,
                "Monthly report input must be a FinancialAnalysisSnapshot",
            )
        try:
            core = self.skill.build_core(snapshot)
        except ReportInputError as exc:
            raise SkillExecutionError(
                SkillErrorCode.REPORT_INPUT_INCOMPLETE,
                str(exc),
            ) from exc

        request = self._build_request(core)
        for attempt in range(self.max_retries + 1):
            try:
                response = await self.provider.generate(request)
            except LLMProviderError as exc:
                raise SkillExecutionError(
                    SkillErrorCode.SKILL_LLM_PROVIDER_ERROR,
                    "Narrative provider request failed",
                ) from exc
            if response.tool_calls:
                raise SkillExecutionError(
                    SkillErrorCode.SKILL_UNEXPECTED_TOOL_CALL,
                    "MonthlySpendingReportSkill cannot call tools",
                )
            try:
                if not response.content:
                    raise ValueError("Narrative response is empty")
                draft = ReportNarrativeDraft.model_validate(
                    self._parse_json(response.content)
                )
                self._validate_narrative(draft, core)
                return MonthlySpendingReport(
                    **core.model_dump(),
                    headline=draft.headline,
                    insights=draft.insights,
                )
            except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
                if attempt >= self.max_retries:
                    break
                request = request.model_copy(deep=True)
                request.messages.append(
                    LLMMessage(
                        role="user",
                        content=self._build_correction_message(core),
                    )
                )
        raise SkillExecutionError(
            SkillErrorCode.REPORT_NARRATIVE_VALIDATION_FAILED,
            "Narrative failed structured grounding validation",
        )

    async def execute_registered(
        self,
        definition: SkillDefinition,
        snapshot: FinancialAnalysisSnapshot,
    ) -> MonthlySpendingReport:
        expected = self.skill.definition
        if (
            definition.skill_id != expected.skill_id
            or definition.version != expected.version
            or definition.input_schema is not expected.input_schema
            or definition.output_schema is not expected.output_schema
            or definition.allowed_tools
        ):
            raise SkillExecutionError(
                SkillErrorCode.REPORT_INPUT_INCOMPLETE,
                "Registered skill definition does not match the executable skill",
            )
        return await self.execute(snapshot)

    def _build_request(self, core: MonthlySpendingReportCore) -> LLMRequest:
        evidence_refs = sorted(self._valid_evidence_refs(core))
        payload = {
            "report_core": core.model_dump(mode="json"),
            "allowed_evidence_refs": evidence_refs,
            "output_schema": {
                "headline": "不含数字的中文标题",
                "insights": [
                    {
                        "type": "STRUCTURE|CHANGE|TRANSACTION|DATA_QUALITY",
                        "title": "不含数字的中文标题",
                        "narrative": "不含数字的中文洞察",
                        "evidence_refs": ["allowed_evidence_refs 中的完整字符串"],
                    }
                ],
            },
            "insight_count": "2..5",
        }
        return LLMRequest(
            messages=[
                LLMMessage(
                    role="system",
                    content=MONTHLY_SPENDING_REPORT_INSTRUCTIONS,
                ),
                LLMMessage(
                    role="user",
                    content=json.dumps(payload, ensure_ascii=False),
                ),
            ],
            tools=[],
        )

    @classmethod
    def _build_correction_message(cls, core: MonthlySpendingReportCore) -> str:
        allowed_refs = sorted(cls._valid_evidence_refs(core))
        change_ref = (
            "period_comparison.absolute_change"
            if core.period_comparison is not None
            else "data_quality.status"
        )
        correction = {
            "instruction": "上一份输出未通过确定性验证，请完全重写并且只输出 JSON。",
            "hard_rules": [
                "headline、title、narrative 均不得含数字。",
                "禁止字符：0123456789０１２３４５６７８９零〇一二三四五六七八九十百千万亿两。",
                "insights 数量为两到五条。",
                "evidence_refs 必须逐字从 allowed_evidence_refs 复制。",
                "不得输出 Markdown、解释或未知类别。",
            ],
            "allowed_evidence_refs": allowed_refs,
            "valid_shape_example": {
                "headline": "本月消费结构与变化概览",
                "insights": [
                    {
                        "type": "STRUCTURE",
                        "title": "主要支出类别较为集中",
                        "narrative": "消费支出主要集中在排名靠前的类别。",
                        "evidence_refs": ["overview.total_spending"],
                    },
                    {
                        "type": "CHANGE",
                        "title": "整体支出变化值得关注",
                        "narrative": "期间对比显示整体支出发生明显变化。",
                        "evidence_refs": [change_ref],
                    },
                ],
            },
        }
        return json.dumps(correction, ensure_ascii=False)

    @classmethod
    def _validate_narrative(
        cls,
        draft: ReportNarrativeDraft,
        core: MonthlySpendingReportCore,
    ) -> None:
        valid_refs = cls._valid_evidence_refs(core)
        known_categories = {item.category for item in core.category_breakdown}
        known_accounts = set(core.scope.account_ids) | {
            item.account_id for item in core.top_transactions
        }
        allowed_uppercase = known_categories | {core.overview.currency}
        text_fields = [draft.headline]
        for insight in draft.insights:
            unknown_refs = set(insight.evidence_refs) - valid_refs
            if unknown_refs:
                raise ValueError("Narrative contains an unknown evidence reference")
            text_fields.extend([insight.title, insight.narrative])
        for text in text_fields:
            if _NUMERIC_TEXT.search(text) or _ENGLISH_NUMERIC_TEXT.search(text):
                raise ValueError("Narrative contains numeric text")
            if set(_CATEGORY_TOKEN.findall(text)) - allowed_uppercase:
                raise ValueError("Narrative contains an unknown category")
            if set(_ACCOUNT_TOKEN.findall(text)) - known_accounts:
                raise ValueError("Narrative contains an unknown account")

    @staticmethod
    def _valid_evidence_refs(core: MonthlySpendingReportCore) -> set[str]:
        refs = {
            "scope.account_ids",
            "overview.total_income",
            "overview.total_spending",
            "overview.transaction_count",
            "overview.currency",
            "data_quality.status",
        }
        if core.period_comparison is not None:
            refs.update(
                {
                    "period_comparison.previous_spending",
                    "period_comparison.absolute_change",
                    "period_comparison.percentage_change",
                }
            )
        for item in core.category_breakdown:
            prefix = f"category_breakdown.{item.category}"
            refs.update(
                {
                    f"{prefix}.amount",
                    f"{prefix}.transaction_count",
                    f"{prefix}.share",
                }
            )
            if item.previous_amount is not None:
                refs.add(f"{prefix}.previous_amount")
            if item.absolute_change is not None:
                refs.add(f"{prefix}.absolute_change")
            if item.percentage_change is not None:
                refs.add(f"{prefix}.percentage_change")
        for item in core.top_transactions:
            prefix = f"top_transactions.{item.transaction_id}"
            refs.update(
                {
                    f"{prefix}.amount",
                    f"{prefix}.category",
                    f"{prefix}.merchant",
                    f"{prefix}.account_id",
                }
            )
        return refs

    @staticmethod
    def _parse_json(content: str) -> Any:
        candidate = content.strip()
        if candidate.startswith("```json") and candidate.endswith("```"):
            candidate = candidate[7:-3].strip()
        elif candidate.startswith("```") and candidate.endswith("```"):
            candidate = candidate[3:-3].strip()
        return json.loads(candidate)
