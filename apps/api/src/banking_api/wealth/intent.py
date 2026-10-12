"""Workflow quantity validation delegates to the shared exact parser."""

import re
from dataclasses import dataclass

from banking_api.wealth.quantity_parser import quantities


@dataclass(frozen=True)
class QuantityIntent:
    quantity: str | None = None
    unit: str | None = None
    redeem_all: bool = False
    message: str | None = None


def extract_quantity(text: str, direction: str) -> QuantityIntent:
    expected = "元" if direction == "PURCHASE" else "份"
    tokens = quantities(text)
    all_requested = bool(
        re.search(r"全部(?:份额|赎回)|(?:赎回|卖出)\s*(?:全部|所有)|所有份额", text)
    )
    if all_requested and direction == "REDEEM" and not tokens:
        return QuantityIntent(redeem_all=True)
    tokens = [t for t in tokens if t.role != "RESERVE"]
    if len(tokens) != 1 or all_requested:
        return QuantityIntent(
            message="数量存在歧义，请明确填写一笔交易的数量及单位"
            if tokens or all_requested
            else f"请补充{'申购金额' if direction == 'PURCHASE' else '赎回份额'}，单位为{expected}"
        )
    token = tokens[0]
    if token.unit != expected:
        return QuantityIntent(
            unit=token.unit,
            message="申购按金额，请补充单位为元的申购金额"
            if direction == "PURCHASE"
            else "当前按份额赎回，请补充单位为份的赎回份额",
        )
    if not token.exact or token.error or not token.value:
        return QuantityIntent(
            unit=token.unit, message=token.error or "请核对一个明确数量，范围或约数不能用于交易"
        )
    return QuantityIntent(quantity=token.value, unit=token.unit)
