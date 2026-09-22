"""One-time independent reference calculation for the committed financial golden file."""

import json
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parents[1] / "apps/api/src/banking_api/mock_bank/data"
OUTPUT_PATH = DATA_DIR / "golden_financial_metrics.json"
VALID_STATUSES = {"POSTED"}
ZERO = Decimal(0)


def load_transactions() -> list[dict[str, Any]]:
    return json.loads((DATA_DIR / "transactions.json").read_text(encoding="utf-8"))


def in_month(item: dict[str, Any], month: str) -> bool:
    return str(item["occurred_at"]).startswith(f"{month}-")


def amount(item: dict[str, Any]) -> Decimal:
    return Decimal(str(item["amount"]))


def valid(item: dict[str, Any]) -> bool:
    return str(item["status"]) in VALID_STATUSES


def spending(item: dict[str, Any]) -> bool:
    return valid(item) and item["direction"] == "DEBIT" and item["category"] != "TRANSFER"


def ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == ZERO:
        return ZERO
    with localcontext() as context:
        context.prec = 28
        return numerator / denominator


def percentage_change(current: Decimal, previous: Decimal) -> Decimal | None:
    if previous == ZERO:
        return None
    with localcontext() as context:
        context.prec = 28
        return (current - previous) / previous * Decimal(100)


def decimal_string(value: Decimal) -> str:
    return str(value)


def monthly_metrics(rows: list[dict[str, Any]], month: str) -> dict[str, Any]:
    period = [item for item in rows if valid(item) and in_month(item, month)]
    income = [
        item
        for item in period
        if item["direction"] == "CREDIT" and item["category"] != "TRANSFER"
    ]
    spent = [item for item in period if spending(item)]
    total = sum((amount(item) for item in spent), ZERO)
    category_amounts: dict[str, Decimal] = defaultdict(lambda: ZERO)
    category_counts: dict[str, int] = defaultdict(int)
    for item in spent:
        category = str(item["category"])
        category_amounts[category] += amount(item)
        category_counts[category] += 1
    categories = [
        {
            "category": category,
            "amount": decimal_string(category_amounts[category]),
            "transaction_count": category_counts[category],
            "share": decimal_string(ratio(category_amounts[category], total)),
        }
        for category in sorted(
            category_amounts, key=lambda name: (-category_amounts[name], name)
        )
    ]
    top = sorted(
        spent,
        key=lambda item: (
            -amount(item),
            datetime.fromisoformat(str(item["occurred_at"]).replace("Z", "+00:00")),
            str(item["transaction_id"]),
        ),
    )[:5]
    return {
        "summary": {
            "period": month,
            "total_income": decimal_string(sum((amount(item) for item in income), ZERO)),
            "total_spending": decimal_string(total),
            "income_transaction_count": len(income),
            "spending_transaction_count": len(spent),
            "currency": "CNY",
        },
        "category_breakdown": {
            "period": month,
            "total_spending": decimal_string(total),
            "currency": "CNY",
            "categories": categories,
        },
        "top_transactions": {
            "period": month,
            "currency": "CNY",
            "transactions": [
                {
                    "transaction_id": str(item["transaction_id"]),
                    "occurred_at": datetime.fromisoformat(
                        str(item["occurred_at"]).replace("Z", "+00:00")
                    )
                    .astimezone(UTC)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "merchant": str(item["merchant"]),
                    "description": str(item["description"]),
                    "category": str(item["category"]),
                    "amount": decimal_string(amount(item)),
                    "currency": str(item["currency"]),
                    "account_id": str(item["account_id"]),
                }
                for item in top
            ],
        },
    }


def comparison(july: dict[str, Any], august: dict[str, Any]) -> dict[str, Any]:
    july_categories = {
        item["category"]: Decimal(item["amount"])
        for item in july["category_breakdown"]["categories"]
    }
    august_categories = {
        item["category"]: Decimal(item["amount"])
        for item in august["category_breakdown"]["categories"]
    }
    current = Decimal(august["summary"]["total_spending"])
    previous = Decimal(july["summary"]["total_spending"])
    return {
        "current_period": "2026-08",
        "previous_period": "2026-07",
        "current_spending": decimal_string(current),
        "previous_spending": decimal_string(previous),
        "absolute_change": decimal_string(current - previous),
        "percentage_change": decimal_string(percentage_change(current, previous)),
        "currency": "CNY",
        "category_changes": [
            {
                "category": category,
                "current_amount": decimal_string(august_categories.get(category, ZERO)),
                "previous_amount": decimal_string(july_categories.get(category, ZERO)),
                "absolute_change": decimal_string(
                    august_categories.get(category, ZERO)
                    - july_categories.get(category, ZERO)
                ),
                "percentage_change": (
                    decimal_string(
                        percentage_change(
                            august_categories.get(category, ZERO),
                            july_categories.get(category, ZERO),
                        )
                    )
                    if july_categories.get(category, ZERO) != ZERO
                    else None
                ),
            }
            for category in sorted(set(july_categories) | set(august_categories))
        ],
    }


def build_fixture() -> dict[str, Any]:
    rows = load_transactions()
    july = monthly_metrics(rows, "2026-07")
    august = monthly_metrics(rows, "2026-08")
    return {
        "fixture_version": "0.3.2",
        "calculation_rules": {
            "valid_transaction_statuses": sorted(VALID_STATUSES),
            "spending_direction": "DEBIT",
            "excluded_spending_categories": ["TRANSFER"],
            "income_direction": "CREDIT",
            "excluded_income_categories": ["TRANSFER"],
            "money_type": "Decimal",
            "period_interval": "left-closed, right-open calendar month",
        },
        "months": {"2026-07": july, "2026-08": august},
        "comparisons": {"2026-07_to_2026-08": comparison(july, august)},
    }


def main() -> None:
    OUTPUT_PATH.write_text(
        json.dumps(build_fixture(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
