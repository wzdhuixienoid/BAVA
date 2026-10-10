"""Bounded deterministic quantity extraction. Units are financial authority."""

import re
from dataclasses import dataclass

from banking_api.wealth.calculation import WealthError, quantity


@dataclass(frozen=True)
class QuantityIntent:
    quantity: str | None = None
    unit: str | None = None
    redeem_all: bool = False
    message: str | None = None


def extract_quantity(text: str, direction: str) -> QuantityIntent:
    expected = "元" if direction == "PURCHASE" else "份"
    tokens = re.findall(
        r"[¥￥]?\s*[-+]?(?:\d[\d,，]*(?:\.\d*)?|NaN|Infinity)(?:\s*[eE][-+]?\d+)?\s*(?:元|份)?",
        text,
        re.IGNORECASE,
    )
    all_requested = bool(
        re.search(r"全部(?:份额|赎回)|(?:赎回|卖出)\s*(?:全部|所有)|所有份额", text)
    )
    if all_requested and direction == "REDEEM" and not tokens:
        return QuantityIntent(redeem_all=True)
    if len(tokens) != 1 or all_requested:
        return QuantityIntent(
            message="数量存在歧义，请明确填写一笔交易的数量及单位"
            if tokens or all_requested
            else f"请补充{'申购金额' if direction == 'PURCHASE' else '赎回份额'}，单位为{expected}"
        )
    token = tokens[0].strip().replace("，", ",")
    unit = (
        "元"
        if token.endswith("元") or token.startswith(("¥", "￥"))
        else "份"
        if token.endswith("份")
        else None
    )
    if token.startswith(("¥", "￥")) and token.endswith("份"):
        return QuantityIntent(unit="份", message="人民币符号与份额单位矛盾，请明确数量及单位")
    if unit != expected:
        return QuantityIntent(
            unit=unit,
            message="申购按金额，请补充单位为元的申购金额"
            if direction == "PURCHASE"
            else "当前按份额赎回，请补充单位为份的赎回份额",
        )
    raw = token.strip("¥￥").removesuffix("元").removesuffix("份").strip()
    if "," in raw and not re.fullmatch(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", raw):
        return QuantityIntent(unit=unit, message="千分位格式不正确，请重新填写数量")
    try:
        value = quantity(raw.replace(",", ""), 2 if direction == "PURCHASE" else 6)
    except (WealthError, ValueError):
        return QuantityIntent(
            unit=unit,
            message="数量必须为有效正数，申购最多两位小数、赎回最多六位小数，且不能超过存储上限",
        )
    return QuantityIntent(quantity=format(value, "f"), unit=unit)
