from typing import Any

DISPLAY_FIELDS = {
    "category_display",
    "share_display",
    "account_display",
    "occurred_at_display",
    "spending_review",
}


def raw_financial_facts(value: Any) -> Any:
    """Keep golden comparisons exact for every raw fact; displays are tested separately."""
    if isinstance(value, dict):
        return {
            key: raw_financial_facts(item)
            for key, item in value.items()
            if key not in DISPLAY_FIELDS
        }
    if isinstance(value, list):
        return [raw_financial_facts(item) for item in value]
    return value
