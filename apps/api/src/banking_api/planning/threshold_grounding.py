"""Finite threshold grammar for the three Condition predicates, using original text only."""

import re
from dataclasses import dataclass
from decimal import Decimal

from banking_api.planning.constraints import has_conditional_control
from banking_api.planning.models import ConditionPredicate, ConditionSpec

METRICS = {
    ConditionPredicate.ACCOUNT_BALANCE_AT_LEAST: r"余额",
    ConditionPredicate.MONTHLY_SPENDING_AT_LEAST: (
        r"(?:本月|这个月|当月|月度)(?:的)?(?:总)?(?:消费|支出|花费)(?:金额)?"
    ),
    ConditionPredicate.SUBSCRIPTION_MONTHLY_COST_AT_LEAST: (
        r"(?:(?:每月|月度|本月)(?:的)?订阅|订阅(?:的)?(?:每月|月度)?)"
        r"(?:费用|月费|成本|花费|费)?"
    ),
}
COMPARISON = r"(?:不少于|不小于|不低于|大于等于|至少|达到|>=|≥)"
NUMBER = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?|[零〇一二两三四五六七八九十百千万]+"
UNIT = r"人民币|CNY|美元|美金|USD|欧元|EUR|英镑|GBP|元|块钱|块"
AMOUNT = re.compile(
    rf"(?P<prefix>[¥￥$€£])?\s*(?P<number>{NUMBER})\s*(?P<unit>{UNIT})?"
    r"(?![0-9A-Za-z,._零〇一二两三四五六七八九十百千万亿点])",
    re.IGNORECASE,
)
# Preserve digit-to-digit commas so malformed grouping cannot become a shorter threshold.
CLAUSE_BOUNDARY = re.compile(r"[，。；;！？!?\n]|(?<![0-9]),|,(?![0-9])")
CURRENCY = {
    "¥": "CNY",
    "￥": "CNY",
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "人民币": "CNY",
    "元": "CNY",
    "块": "CNY",
    "块钱": "CNY",
    "CNY": "CNY",
    "美元": "USD",
    "美金": "USD",
    "USD": "USD",
    "欧元": "EUR",
    "EUR": "EUR",
    "英镑": "GBP",
    "GBP": "GBP",
}
DIGITS = {
    character: value
    for value, characters in enumerate(
        ("零〇", "一", "二两", "三", "四", "五", "六", "七", "八", "九")
    )
    for character in characters
}


class ThresholdGroundingError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class GroundedConditionThreshold:
    predicate: ConditionPredicate
    amount: Decimal
    currency: str | None
    source_span: tuple[int, int]


def _chinese_integer(literal: str) -> int:
    """Bounded ordinary integers up to 万; reject unsupported/ambiguous numeral forms."""
    if len(literal) > 24 or literal.count("万") > 1:
        raise ValueError("Unsupported Chinese amount")
    if "万" in literal:
        high, low = literal.split("万")
        if not high:
            raise ValueError("Missing 万 multiplier")
        if low and not low.startswith(("零", "〇")) and not any(unit in low for unit in "十百千"):
            raise ValueError("Ambiguous Chinese shorthand")
        return _chinese_integer(high) * 10000 + (_chinese_integer(low.lstrip("零〇")) if low else 0)
    if len(literal) > 1 and literal[-1] in "零〇":
        raise ValueError("Incomplete Chinese amount")
    total, pending, previous_unit = 0, None, 10000
    for index, character in enumerate(literal):
        if character in DIGITS:
            if pending is not None:
                raise ValueError("Ambiguous consecutive digits")
            pending = DIGITS[character]
            if pending == 0 and total:
                pending = None
        else:
            unit = {"十": 10, "百": 100, "千": 1000}[character]
            if (
                unit >= previous_unit
                or pending == 0
                or (pending is None and not (index == 0 and unit == 10))
            ):
                raise ValueError("Unsupported Chinese unit order")
            total += (pending if pending is not None else 1) * unit
            previous_unit, pending = unit, None
    if pending is not None and previous_unit > 10 and total and literal[-2] not in "零〇":
        raise ValueError("Ambiguous Chinese shorthand")
    return total + (pending or 0)


def normalize_explicit_amount_literals(literal: str) -> Decimal:
    """Normalize a single complete threshold number, never search business action amounts."""
    if len(literal) > 64 or not re.fullmatch(NUMBER, literal):
        raise ValueError("Unsupported explicit amount")
    if literal[0].isascii():
        return Decimal(literal.replace(",", ""))
    return Decimal(_chinese_integer(literal))


class ConditionThresholdGroundingValidator:
    def _clauses(self, text: str) -> list[tuple[int, str]]:
        clauses, start = [], 0
        for boundary in CLAUSE_BOUNDARY.finditer(text):
            clauses.append((start, text[start : boundary.start()]))
            start = boundary.end()
        clauses.append((start, text[start:]))
        conditional = [
            (offset, clause) for offset, clause in clauses if has_conditional_control(clause)
        ]
        return conditional or clauses

    def extract(self, user_request: str) -> list[GroundedConditionThreshold]:
        thresholds = []
        for offset, clause in self._clauses(user_request):
            for predicate, metric in METRICS.items():
                for match in re.finditer(metric + r"\s*" + COMPARISON + r"\s*", clause):
                    amount = AMOUNT.match(clause, match.end())
                    if amount is None:
                        continue
                    try:
                        value = normalize_explicit_amount_literals(amount["number"])
                    except ValueError:
                        continue
                    prefix = CURRENCY.get(amount["prefix"] or "")
                    unit = CURRENCY.get((amount["unit"] or "").upper())
                    if prefix and unit and prefix != unit:
                        continue
                    thresholds.append(
                        GroundedConditionThreshold(
                            predicate,
                            value,
                            prefix or unit,
                            (offset + match.start(), offset + amount.end()),
                        )
                    )
        return thresholds

    def require_explicit_thresholds(self, user_request: str) -> None:
        grounded = self.extract(user_request)
        for offset, clause in self._clauses(user_request):
            if not has_conditional_control(clause):
                continue
            for predicate, metric in METRICS.items():
                for match in re.finditer(metric, clause):
                    start = offset + match.start()
                    if not any(
                        item.predicate == predicate and item.source_span[0] == start
                        for item in grounded
                    ):
                        raise ThresholdGroundingError("PLAN_CONDITION_THRESHOLD_REQUIRED")

    def validate(self, user_request: str, spec: ConditionSpec) -> GroundedConditionThreshold:
        candidates = [
            item for item in self.extract(user_request) if item.predicate == spec.predicate
        ]
        matching = [item for item in candidates if item.amount == Decimal(spec.threshold)]
        if not matching:
            raise ThresholdGroundingError("PLAN_CONDITION_THRESHOLD_NOT_GROUNDED")
        # Do not guess which of multiple incompatible thresholds was intended.
        if len({(item.amount, item.currency) for item in candidates}) != 1:
            raise ThresholdGroundingError("PLAN_CONDITION_THRESHOLD_NOT_GROUNDED")
        grounded = matching[0]
        if spec.currency is not None and spec.currency != grounded.currency:
            raise ThresholdGroundingError("PLAN_CONDITION_CURRENCY_NOT_GROUNDED")
        return grounded
