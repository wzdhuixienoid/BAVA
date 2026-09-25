from decimal import Decimal


def amount_is_valid(amount: Decimal | None) -> bool:
    if amount is None or amount <= 0:
        return False
    return amount.as_tuple().exponent >= -2


def normalize_hint(value: str) -> str:
    return "".join(value.casefold().split())
