"""Explicit needs and bounded follow-up merging, using the business clock."""

import re
from datetime import timedelta
from decimal import Decimal

from banking_api.wealth.calculation import CN, quantity
from banking_api.wealth.requirements import parse_requirements
from banking_api.wealth.schemas import WealthNeeds


def collect_needs(body, now, previous=None):
    text = body.needs or body.query if hasattr(body, "query") else body.needs
    result = previous.model_copy(deep=True) if previous else WealthNeeds()
    result.changed_fields = []
    result.raw = text if not previous else previous.raw + "；本次补充：" + text
    # Budget units belong to the amount: 10000万 is one hundred million yuan.
    money = re.compile(
        r"(?<![\d.])(?P<prefix>[¥￥]\s*)?(?P<number>[+-]?\d+(?:,\d{3})*(?:\.\d+)?)"
        r"\s*(?P<unit>亿元?|万元?|[wW]|元|人民币|块钱?)?(?![\d])"
    )
    matches = [m for m in money.finditer(text) if m["prefix"] or m["unit"]]
    if not matches:
        bare = re.search(r"预算\s*(?:是|为|有|约|大概|：|:)?\s*([\d,]+(?:\.\d+)?)(?![\d.])", text)
        if bare:
            matches = [bare]
    supplied_amount = body.amount
    if not supplied_amount and len(matches) == 1:
        match = matches[0]
        if "number" in match.groupdict():
            value = Decimal(match["number"].replace(",", ""))
            unit = match["unit"] or "元"
            value *= Decimal(
                "100000000"
                if unit.startswith("亿")
                else "10000"
                if unit.startswith("万") or unit in "wW"
                else "1"
            )
        else:
            value = Decimal(match[1].replace(",", ""))
        supplied_amount = format(value, "f")
    if supplied_amount:
        result.amount = str(quantity(supplied_amount))
        result.changed_fields.append("amount")
    if body.account_id:
        result.account_id = body.account_id
        result.changed_fields.append("account_id")
    parsed_text = text
    for match in reversed(matches):
        parsed_text = parsed_text[: match.start()] + "预算" + parsed_text[match.end() :]
    parsed_text = re.sub(r"如果买|预算为|打算买", "预算", parsed_text)
    # Naming a product for objective comparison is not a statement of risk preference.
    parsed_text = re.sub(
        r"(?:演示)?(?:稳享日日|稳享周周|稳健优选|均衡优选|均衡周享|进取成长|进取周享|高波动精选)",
        "指定产品",
        parsed_text,
    )
    constraint = parse_requirements(parsed_text)
    if previous:
        old = result.constraints
        # Preferences can change; hard constraints persist unless explicitly revoked.
        for key in (
            "principal_guarantee",
            "no_principal_loss",
            "immediate_cash",
            "within_week",
            "avoid_weekly",
        ):
            setattr(constraint, key, getattr(constraint, key) or getattr(old, key))
        if re.search(r"不要求保本|不需要保本", text):
            constraint.principal_guarantee = False
        if re.search(r"(?:^|[，。；;])\s*(?:我)?(?:可以|愿意)?接受本金损失|可以亏本金", text):
            constraint.no_principal_loss = False
        if "不需要马上" in text:
            constraint.immediate_cash = False
        constraint.excluded_risks = sorted(set(old.excluded_risks + constraint.excluded_risks))
        constraint.maximum_risk = min(old.maximum_risk, constraint.maximum_risk)
        constraint.preferred_risk = constraint.preferred_risk or old.preferred_risk
    result.constraints = constraint
    local = now.astimezone(CN)
    liquidity = re.search(
        r"下周(?:可能)?(?:要)?用钱|一周内|随时(?:可能)?用钱|不需要马上用钱|(?:持有|投资|放)(?:\d+|一|三|半)(?:个月|年|天)|\d{4}-\d{2}-\d{2}(?:.{0,4}用钱)?",
        text,
    )
    if liquidity:
        result.liquidity_raw = liquidity[0]
        result.changed_fields.append("liquidity")
        result.use_date_from = result.use_date_to = None
        result.constraints.within_week = bool(re.search(r"下周|一周内", liquidity[0]))
        result.constraints.immediate_cash = bool(re.search(r"随时", liquidity[0]))
        if "下周" in liquidity[0]:
            start = local.date() + timedelta(days=7 - local.weekday())
            result.use_date_from, result.use_date_to = (
                start.isoformat(),
                (start + timedelta(days=6)).isoformat(),
            )
            result.constraints.within_week = True
            result.liquidity_basis = (
                "下周解析为北京时间下一个周一至周日；"
                "可能用钱并非承诺持有到周日，按最早用款日谨慎筛选。"
            )
        elif "一周内" in liquidity[0]:
            result.use_date_from, result.use_date_to = (
                local.date().isoformat(),
                (local.date() + timedelta(days=7)).isoformat(),
            )
            result.liquidity_basis = "一周内可能任一天用钱，不能承诺异步资金能及时到达。"
        elif re.search(r"\d{4}-\d{2}-\d{2}", liquidity[0]):
            from datetime import date

            value = re.search(r"\d{4}-\d{2}-\d{2}", liquidity[0])[0]
            date.fromisoformat(value)
            result.use_date_from = result.use_date_to = value
            result.liquidity_basis = "用户明确给出的北京时间用款日期。"
        else:
            result.liquidity_basis = "保留原始期限表述；未确认具体用款日期。"
    if "费用优先" in text or "手续费低" in text:
        result.priority = "FEES"
    if "流动性优先" in text or "不能等周一" in text:
        result.priority = "LIQUIDITY"
    if re.search(r"收益(?:更高|高一些|潜力)|(?:赚得|赚的|赚)(?:比较多|更多|多一些)", text):
        result.return_goal = "HIGHER_POTENTIAL"
    loss = re.search(r"(?:可以|愿意|能够|可)?接受(?:部分|一定|少量)亏损", text)
    if loss:
        result.loss_tolerance_raw = loss[0]
    result.missing_fields = [
        key
        for key, value in [
            ("amount", result.amount),
            ("liquidity", result.liquidity_raw),
            ("account", result.account_id),
        ]
        if not value
    ]
    result.assumptions = [
        "未指定本次风险偏好时，参考问卷投资目标；测评等级只作为上限。",
        "未提供账户时不判断可用余额。",
    ]
    result.clarification_questions = []
    if not result.amount:
        result.clarification_questions.append("这次计划投资多少元？")
    if not result.liquidity_raw:
        result.clarification_questions.append("这笔钱最早什么时候可能用到？")
    if result.loss_tolerance_raw:
        result.clarification_questions.append("你提到可以接受部分亏损，最多能接受本金损失多少？")
    if result.use_date_from and result.use_date_from != result.use_date_to:
        result.clarification_questions.insert(
            0, ("这段时间内最早哪一天可能需要现金？确认后可进一步判断到账是否来得及。")
        )
    if len(matches) > 1 and not body.amount:
        result.amount = None
        result.constraints.ambiguous = True
        result.clarification_questions = ["出现多个金额，请明确本次预算。"]
    if result.constraints.ambiguous and len(matches) <= 1:
        result.clarification_questions = ["请明确本次风险偏好和用款时间；有无法确定的条件。"]
    result.clarification_questions = result.clarification_questions[:2]
    return result
