"""Customer-facing recommendation method over already validated facts, with no tools."""

from decimal import Decimal

from banking_api.skills.models import SkillDefinition
from banking_api.wealth.schemas import WealthAnalysis, WealthAnalysisBlock, WealthCustomerResponse


class WealthRecommendationSkill:
    definition = SkillDefinition(
        skill_id="skill:wealth-recommendation",
        version=1,
        description="结合本次预算、期限与产品事实，用简明正文解释推荐和取舍。",
        input_schema=WealthAnalysis,
        output_schema=WealthCustomerResponse,
        allowed_tools=(),
    )

    def present(self, analysis: WealthAnalysis) -> WealthCustomerResponse:
        """Format supplied facts; never infer assets, increase eligibility or change order."""
        response = WealthCustomerResponse(
            headline=analysis.conclusion,
            questions=list(analysis.needs.clarification_questions),
            budget_display=(
                f"{Decimal(analysis.needs.amount):,.2f} 元" if analysis.needs.amount else None
            ),
            liquidity_display=analysis.needs.liquidity_raw,
        )
        if (
            analysis.needs.return_goal
            and analysis.candidates
            and analysis.result_kind == "RECOMMENDATION"
        ):
            response.headline = (
                "你更看重收益潜力。"
                + ("你也提到可以承担部分亏损。" if analysis.needs.loss_tolerance_raw else "")
                + "下面几款在费用、风险和开放时间上各有取舍，可以放在一起看。"
                + "不过，现有资料不能判断哪款未来一定赚得更多。"
            )
        if analysis.result_kind == "EDUCATION":
            response.paragraphs = list(analysis.blocks)
            return response
        for candidate in analysis.candidates:
            advantages = [
                a
                for a in candidate.advantages
                if not a.startswith("目前只") and "没有已确认的全面优势" not in a
            ]
            # Shared principal/cash risks appear once below; keep product-specific
            # window and relative fee limitations in the main customer prose.
            details = advantages[:2] + candidate.limitations[2:]
            if analysis.result_kind == "CATALOGUE":
                # No relative ranking or questionnaire preference is implied by the directory.
                continue
            if len(candidate.product.terms.get("weekdays", [])) == 5:
                details.append("可申请的日子较多，但赎回款仍需等待到账，不能当作随时可用的现金。")
            if not candidate.fee_scenario:
                details.append(candidate.product.fees_display + "。")
            if not details:
                continue
            response.paragraphs.append(
                WealthAnalysisBlock(
                    block_id=candidate.fact_id,
                    title=candidate.product.name,
                    text=f"{candidate.product.name}：" + " ".join(details),
                    fact_ids=[candidate.fact_id],
                    evidence_ids=candidate.evidence_ids,
                )
            )
        if analysis.candidates:
            response.paragraphs.append(
                WealthAnalysisBlock(
                    block_id="risk-and-cash",
                    title="风险与用款",
                    text="净值可能下跌，本金和收益都没有保证；赎回款需要等待到账。",
                    fact_ids=[c.fact_id for c in analysis.candidates],
                    evidence_ids=list(
                        dict.fromkeys(e for c in analysis.candidates for e in c.evidence_ids)
                    ),
                )
            )
        return response
