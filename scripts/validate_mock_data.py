"""Validate the committed synthetic banking dataset."""

import json
import re
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

DATA_DIR = Path(__file__).parents[1] / "apps/api/src/banking_api/mock_bank/data"
FULL_CARD_PATTERN = re.compile(r"(?<!\d)\d{12,19}(?!\d)")


def load(name: str) -> list[dict[str, object]]:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def validate() -> dict[str, int]:
    accounts = load("accounts.json")
    transactions = load("transactions.json")
    payees = load("payees.json")
    subscriptions = load("subscriptions.json")

    for rows, key in (
        (accounts, "account_id"),
        (transactions, "transaction_id"),
        (payees, "payee_id"),
        (subscriptions, "subscription_id"),
    ):
        ids = [row[key] for row in rows]
        assert len(ids) == len(set(ids)), f"duplicate {key}"

    account_ids = {row["account_id"] for row in accounts}
    assert all(row["account_id"] in account_ids for row in transactions)
    assert len(transactions) >= 1000
    months = Counter(str(row["occurred_at"])[:7] for row in transactions)
    expected_months = {f"2025-{month:02d}" for month in range(1, 13)} | {
        f"2026-{month:02d}" for month in range(1, 10)
    }
    assert expected_months <= months.keys(), "missing complete historical month"
    assert all(months[month] >= 20 for month in expected_months)
    assert all(
        datetime.fromisoformat(str(row["occurred_at"]).replace("Z", "+00:00"))
        <= datetime(2026, 10, 7, 23, 59, 59, tzinfo=UTC)
        for row in transactions
    )
    assert {"POSTED", "PENDING", "REVERSED"} <= {row["status"] for row in transactions}
    assert {
        "SALARY",
        "BONUS",
        "REFUND",
        "FOOD",
        "HOUSING",
        "TRAVEL",
        "SHOPPING",
        "TRANSPORT",
        "UTILITIES",
        "HEALTH",
        "ENTERTAINMENT",
        "SUBSCRIPTION",
        "TRANSFER",
        "OTHER",
    } <= {row["category"] for row in transactions}
    assert any(row["account_id"] == "acc_salary" for row in accounts)
    assert any(
        count >= 2 for count in Counter(row["display_name"] for row in payees).values()
    )
    assert all(
        row["currency"] == "CNY" for row in accounts + transactions + subscriptions
    )
    assert all(
        row["billing_interval"] in {"MONTHLY", "ANNUAL"} for row in subscriptions
    )
    assert all(isinstance(row["cancellable"], bool) for row in subscriptions)
    assert all(row["status"] in {"ACTIVE", "CANCELLED"} for row in subscriptions)

    for row in accounts:
        Decimal(str(row["balance"]))
    for row in transactions:
        try:
            assert Decimal(str(row["amount"])) > 0
        except InvalidOperation as exc:
            raise AssertionError("invalid transaction amount") from exc
    for row in subscriptions:
        assert Decimal(str(row["amount"])) >= 0

    serialized = json.dumps(
        accounts + transactions + payees + subscriptions, ensure_ascii=False
    )
    assert not FULL_CARD_PATTERN.search(serialized), (
        "dataset contains a full card-like number"
    )
    assert all(str(row["masked_number"]).startswith("****") for row in accounts)
    assert all(str(row["masked_account"]).startswith("****") for row in payees)

    return {
        "accounts": len(accounts),
        "transactions": len(transactions),
        "payees": len(payees),
        "subscriptions": len(subscriptions),
    }


if __name__ == "__main__":
    print(json.dumps(validate(), ensure_ascii=False, sort_keys=True))
