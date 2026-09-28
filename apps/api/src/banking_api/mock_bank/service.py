import json
from decimal import Decimal
from pathlib import Path
from typing import Any


class AccountNotFoundError(Exception):
    pass


class MockBankService:
    """Read-only access to committed, entirely synthetic bank fixtures."""

    def __init__(
        self,
        data_dir: Path | None = None,
        *,
        fixture_user_ids: frozenset[str] = frozenset({"dev-user-001"}),
    ) -> None:
        directory = data_dir or Path(__file__).with_name("data")
        self._accounts: list[dict[str, Any]] = json.loads(
            (directory / "accounts.json").read_text(encoding="utf-8")
        )
        self._transactions: list[dict[str, Any]] = json.loads(
            (directory / "transactions.json").read_text(encoding="utf-8")
        )
        payees_path = directory / "payees.json"
        self._payees: list[dict[str, Any]] = (
            json.loads(payees_path.read_text(encoding="utf-8")) if payees_path.exists() else []
        )
        subscriptions_path = directory / "subscriptions.json"
        self._subscriptions: list[dict[str, Any]] = (
            json.loads(subscriptions_path.read_text(encoding="utf-8"))
            if subscriptions_path.exists()
            else []
        )
        self._accounts = self._scope_fixture(self._accounts, fixture_user_ids)
        self._transactions = self._scope_fixture(self._transactions, fixture_user_ids)
        self._payees = self._scope_fixture(self._payees, fixture_user_ids)
        self._subscriptions = self._scope_fixture(self._subscriptions, fixture_user_ids)

    @staticmethod
    def _scope_fixture(
        items: list[dict[str, Any]], user_ids: frozenset[str]
    ) -> list[dict[str, Any]]:
        scoped: list[dict[str, Any]] = []
        for item in items:
            if "user_id" in item:
                scoped.append(dict(item))
            else:
                scoped.extend({**item, "user_id": user_id} for user_id in user_ids)
        return scoped

    def list_accounts(self, *, user_id: str) -> list[dict[str, Any]]:
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
            if item["user_id"] == user_id
        ]

    def get_balance(self, account_id: str, *, user_id: str) -> dict[str, Any]:
        account = next(
            (
                item
                for item in self._accounts
                if item["account_id"] == account_id and item["user_id"] == user_id
            ),
            None,
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

    def list_transactions(self, *, user_id: str) -> list[dict[str, Any]]:
        """Return copies of synthetic transactions for internal domain services."""
        return [dict(item) for item in self._transactions if item["user_id"] == user_id]

    def list_subscriptions(self, *, user_id: str) -> list[dict[str, Any]]:
        """Return authoritative synthetic subscription contracts for one Principal."""
        return [dict(item) for item in self._subscriptions if item["user_id"] == user_id]

    def get_subscription(self, subscription_id: str, *, user_id: str) -> dict[str, Any] | None:
        return next(
            (
                dict(item)
                for item in self._subscriptions
                if item["subscription_id"] == subscription_id and item["user_id"] == user_id
            ),
            None,
        )

    @staticmethod
    def _normalize(value: str) -> str:
        return "".join(value.casefold().split())

    def search_payees(self, query: str, *, user_id: str) -> list[dict[str, Any]]:
        """Bounded exact matching only; no fuzzy or model-selected resolution."""
        normalized = self._normalize(query)
        return [
            dict(item)
            for item in self._payees
            if item["user_id"] == user_id
            and (
                self._normalize(item["display_name"]) == normalized
                or self._normalize(item["phone_alias"]) == normalized
            )
        ][:10]
