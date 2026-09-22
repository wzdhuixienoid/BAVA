"""Validate the committed synthetic banking dataset."""

import json
import re
from collections import Counter
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
    assert 100 <= len(transactions) <= 150
    assert any(row["account_id"] == "acc_salary" for row in accounts)
    assert any(count >= 2 for count in Counter(row["display_name"] for row in payees).values())
    assert all(row["currency"] == "CNY" for row in accounts + transactions + subscriptions)
    assert all(1 <= int(row["billing_day"]) <= 28 for row in subscriptions)
    assert all(row["status"] in {"ACTIVE", "CANCELLED"} for row in subscriptions)

    for row in accounts:
        Decimal(str(row["balance"]))
    for row in transactions:
        try:
            assert Decimal(str(row["amount"])) > 0
        except InvalidOperation as exc:
            raise AssertionError("invalid transaction amount") from exc
    for row in subscriptions:
        assert Decimal(str(row["monthly_amount"])) >= 0

    serialized = json.dumps(accounts + transactions + payees + subscriptions, ensure_ascii=False)
    assert not FULL_CARD_PATTERN.search(serialized), "dataset contains a full card-like number"
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
