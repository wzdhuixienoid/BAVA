"""Conservative Chinese recommendation constraints, shared by HTTP and Agent tools."""

import re

from pydantic import BaseModel, Field


class RecommendationConstraints(BaseModel):
    principal_guarantee: bool = False
    no_principal_loss: bool = False
    preferred_risk: int | None = None
    excluded_risks: list[int] = Field(default_factory=list)
    maximum_risk: int = 5
    immediate_cash: bool = False
    within_week: bool = False
    avoid_weekly: bool = False
    ambiguous: bool = False
    reasons: list[str] = Field(default_factory=list)


def parse_requirements(needs: str) -> RecommendationConstraints:
    result = RecommendationConstraints()
    clauses = [c.strip() for c in re.split(r"[，,。；;！!？?]|但是|但|而且", needs) if c.strip()]
    preferences = set()
    understood = not clauses
    for clause in clauses:
        recognized = bool(
            re.search(
                r"测评|购买|申购|想买|要买|可以买|指定产品|推荐|比较|对比|为什么|优势|费用|手续费|起购|有什么|买理财|预算|期限|持有|投资|收益|赚钱|赚得|赚的|亏损|下周|用钱|适合|能买|这两款|第一款|第二款|现在|上次|多少|稳享|优选|周享|成长|精选|R[1-5]|\d{4}-\d{2}-\d{2}",
                clause,
                re.I,
            )
        )
        cap = re.search(r"R([1-5])\s*(?:以下|以内|及以下)", clause, re.I)
        if cap:
            result.maximum_risk = min(result.maximum_risk, int(cap[1]))
        if "不能等周一" in clause or "不要周开放" in clause:
            result.avoid_weekly = True
        if "下周" in clause:
            result.within_week = True
        if re.search(
            r"收益.{0,6}(?:一定|保证)|(?:必须|保证|一定).{0,6}(?:收益|赚钱|盈利)|稳赚", clause
        ):
            result.ambiguous = True
            result.reasons.append("当前产品不能保证未来收益，无法满足必然获利或超过市场的要求")
        if "保本" in clause:
            recognized = True
            if not re.search(r"(?:不要求|不需要|无需|不用|不必|不追求)\s*保本", clause):
                result.principal_guarantee = True
        if re.search(
            r"(?:不能|不可|不要|不接受|不允许|拒绝).{0,6}(?:亏|损失|亏损).{0,3}(?:本金)?|本金.{0,4}(?:不能|不可).{0,3}(?:亏|损失)",
            clause,
        ):
            recognized = True
            result.no_principal_loss = True
        if re.search(r"(?:可以|能够|可|愿意|接受|承担).{0,6}(?:波动|损失|亏损)|风险承受", clause):
            recognized = True
        if re.search(
            r"(?:即时|马上|立即|随时).{0,5}(?:用钱|使用|用资金|到账|用款)|即时用钱", clause
        ):
            recognized = True
            if not re.search(
                r"(?:不需要|不用|不急|无需|不要求).{0,4}(?:即时|马上|立即|随时)", clause
            ):
                result.immediate_cash = True
        if re.search(r"一周内|7\s*天|七天|不足一周", clause):
            recognized = True
            if not re.search(r"(?:不需要|不用|无需).{0,4}(?:一周内|7\s*天|七天)", clause):
                result.within_week = True
        for word, risk in (("保守", 1), ("稳健", 2), ("均衡", 3), ("进取", 4), ("高风险", 4)):
            for m in re.finditer(word, clause):
                recognized = True
                prefix = clause[: m.start()]
                if re.search(r"(?:不要|不想|不考虑|排除|拒绝|避免|不接受|不选|不喜欢)\s*$", prefix):
                    result.excluded_risks.extend([4, 5] if risk == 4 else [risk])
                else:
                    preferences.add(risk)
                    if re.search(r"(?:只要|仅要|只选|仅选)\s*$", prefix):
                        result.maximum_risk = min(result.maximum_risk, risk)
        if clause in {
            "推荐",
            "推荐理财",
            "理财",
            "帮我推荐",
            "根据我的测评推荐",
            "适合我的",
            "推荐适合我的理财",
        }:
            recognized = True
        if not recognized:
            result.ambiguous = True
        understood = understood or recognized
    result.excluded_risks = sorted(set(result.excluded_risks))
    if len(preferences) > 1 or preferences.intersection(result.excluded_risks):
        result.ambiguous = True
    elif preferences:
        result.preferred_risk = next(iter(preferences))
    if not understood or result.ambiguous:
        result.ambiguous = True
        result.reasons.append("本次需求存在矛盾或无法可靠解释，请补充明确风险偏好和用款时间")
    if result.principal_guarantee or result.no_principal_loss:
        result.reasons.append("本次要求保本或不能接受本金损失，当前净值型模拟产品均不适配")
    if result.immediate_cash:
        result.reasons.append("本次要求即时用钱或到账，异步到账产品均不适配")
    return result
