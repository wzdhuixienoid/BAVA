import json
from decimal import Decimal
from pathlib import Path
from typing import Any


class AccountNotFoundError(Exception):
    pass


class MockBankService:
    """Read-only access to committed, entirely synthetic bank fixtures."""

    def __init__(self, data_dir: Path | None = None) -> None:
        directory = data_dir or Path(__file__).with_name("data")
        self._accounts: list[dict[str, Any]] = json.loads(
            (directory / "accounts.json").read_text(encoding="utf-8")
        )
        self._transactions: list[dict[str, Any]] = json.loads(
            (directory / "transactions.json").read_text(encoding="utf-8")
        )

    def list_accounts(self) -> list[dict[str, Any]]:
        return [
            {
                "account_id": item["account_id"],
                "display_name": item["display_name"],
                "account_type": item["account_type"],
                "masked_number": item["masked_number"],
                "currency": item["currency"],
                "status": item["status"],
            }
            for item in self._accounts
        ]

    def get_balance(self, account_id: str) -> dict[str, Any]:
        account = next(
            (item for item in self._accounts if item["account_id"] == account_id), None
        )
        if account is None:
            raise AccountNotFoundError(f"Account not found: {account_id}")
        return {
            "account_id": account["account_id"],
            "display_name": account["display_name"],
            "masked_number": account["masked_number"],
            "currency": account["currency"],
            "balance": Decimal(account["balance"]),
        }

    def list_transactions(self) -> list[dict[str, Any]]:
        """Return copies of synthetic transactions for internal domain services."""
        return [dict(item) for item in self._transactions]
