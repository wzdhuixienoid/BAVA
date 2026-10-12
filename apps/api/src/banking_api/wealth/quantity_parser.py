"""Exact Decimal quantities shared by needs and workflow input. No prefix matches."""

import re
from decimal import Decimal

from pydantic import BaseModel

from banking_api.wealth.calculation import WealthError, quantity

DIGITS = dict(zip("零〇一二两三四五六七八九", [0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9], strict=True))
UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000}
TOKEN = re.compile(
    r"(?<![a-zA-Z\d.])(?:[¥￥]\s*)?[+-]?(?:\d[\d,，]*(?:\.\d+)?"
    r"|[零〇一二两三四五六七八九十百千万亿]+|NaN|Infinity)\s*"
    r"(?:[kKwW]|千|万|亿)?\s*(?:元|人民币|块钱?|份)?(?![a-zA-Z])",
    re.I,
)


class QuantityMention(BaseModel):
    original: str
    value: str | None = None
    unit: str | None = None
    role: str = "UNSPECIFIED"
    exact: bool = True
    error: str | None = None


def chinese_number(raw: str) -> Decimal:
    total = section = current = 0
    for char in raw:
        if char in DIGITS:
            current = DIGITS[char]
        elif char in UNITS:
            unit = UNITS[char]
            if unit < 10000:
                section += (current or 1) * unit
            elif unit == 10000:
                total += (section + current) * unit
                section = 0
            else:
                total = (total + section + current) * unit
                section = 0
            current = 0
        else:
            raise ValueError("unsupported numeral")
    return Decimal(total + section + current)


def parse_quantity(raw: str, *, role: str = "UNSPECIFIED") -> QuantityMention:
    token = raw.strip().replace("，", ",")
    unit = (
        "份"
        if token.endswith("份")
        else "元"
        if re.search(r"元|人民币|块|[¥￥]|[千百十万亿kKwW]", token)
        else None
    )
    result = QuantityMention(original=raw, unit=unit, role=role)
    if re.search(r"约|大概|左右|几|到|至|不超过|最多|至少|以内|以上|以下|~|～", token):
        result.exact = False
        return result
    if token.startswith(("¥", "￥")) and unit == "份":
        result.error = "人民币符号与份额单位矛盾"
        return result
    token = re.sub(r"^(?:[¥￥]\s*)", "", token)
    token = re.sub(r"(?:人民币|块钱?|元|份)$", "", token).strip()
    try:
        if re.fullmatch(r"[零〇一二两三四五六七八九十百千万亿]+", token):
            value = chinese_number(token)
        else:
            m = re.fullmatch(r"([+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*([kKwW千亿万]?)", token)
            if not m:
                raise ValueError("invalid unit or number")
            if "," in m[1] and not re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", m[1]):
                raise ValueError("invalid thousands separator")
            scale = {"千": 1000, "k": 1000, "万": 10000, "w": 10000, "亿": 100000000}
            value = Decimal(m[1].replace(",", "")) * Decimal(scale.get(m[2].lower(), 1))
        result.value = format(quantity(format(value, "f"), 6 if unit == "份" else 2), "f")
    except (ValueError, WealthError):
        result.error = "数量必须为有效正数，精度与金额上限不能超出允许范围"
    return result


def quantities(text: str) -> list[QuantityMention]:
    # Use Chinese-aware boundaries, not \\w (which includes all Chinese letters).
    pattern = TOKEN.pattern.replace(r"(?<![\w.])", r"(?<![a-zA-Z\d.])")
    found = []
    for m in re.finditer(pattern, text, re.I):
        prefix, suffix = text[max(0, m.start() - 12) : m.start()], text[m.end() : m.end() + 8]
        raw = m[0].strip().rstrip(",，")
        if re.search(r"^\s*(?:%|％|天|日|个月|月|年|号)", suffix) or re.search(r"[RrCc]$", prefix):
            continue
        if re.search(r"\d{4}-\d{2}-\d{2}", text[max(0, m.start() - 10) : m.end() + 10]):
            continue
        item = parse_quantity(raw)
        if item.unit is None:
            if re.search(r"预算\s*(?:是|为|有|：|:)?\s*$", prefix):
                item.unit = "元"
            else:
                continue
        if re.search(r"约|大概|不超过|最多|至少|几$", prefix) or re.search(
            r"^\s*(?:到|至|左右)", suffix
        ):
            item.exact = False
            item.value = None
        item.role = "RESERVE" if re.search(r"应急|留作|备用", prefix + suffix) else "BUDGET"
        found.append(item)
    return found
