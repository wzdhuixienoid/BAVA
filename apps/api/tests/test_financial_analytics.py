import json
from decimal import Decimal
from pathlib import Path

import pytest

from banking_api.financial.analytics_service import (
    VALID_TRANSACTION_STATUSES,
    FinancialAnalyticsService,
)
from banking_api.financial.errors import FinancialDomainError, FinancialErrorCode
from banking_api.mock_bank.service import MockBankService


@pytest.fixture
def analytics() -> FinancialAnalyticsService:
    return FinancialAnalyticsService(MockBankService())


def write_bank_data(
    directory: Path,
    transactions: list[dict[str, str]],
    *,
    account_currencies: dict[str, str] | None = None,
) -> FinancialAnalyticsService:
    currencies = account_currencies or {"acc_test": "CNY"}
    accounts = [
        {
            "account_id": account_id,
            "display_name": account_id,
            "account_type": "DEBIT",
            "masked_number": "****0000",
            "currency": currency,
            "status": "ACTIVE",
            "balance": "0.00",
        }
        for account_id, currency in currencies.items()
    ]
    (directory / "accounts.json").write_text(json.dumps(accounts), encoding="utf-8")
    (directory / "transactions.json").write_text(
        json.dumps(transactions), encoding="utf-8"
    )
    return FinancialAnalyticsService(MockBankService(directory))


def transaction(
    transaction_id: str,
    amount: str,
    *,
    occurred_at: str = "2026-08-10T00:00:00Z",
    account_id: str = "acc_test",
    currency: str = "CNY",
    direction: str = "DEBIT",
    category: str = "FOOD",
    status: str = "POSTED",
) -> dict[str, str]:
    return {
        "transaction_id": transaction_id,
        "account_id": account_id,
        "occurred_at": occurred_at,
        "merchant": "Synthetic merchant",
        "description": "Synthetic transaction",
        "amount": amount,
        "currency": currency,
        "direction": direction,
        "category": category,
        "status": status,
    }


def test_monthly_summary_separates_income_and_spending_and_excludes_transfer(
    analytics: FinancialAnalyticsService,
) -> None:
    result = analytics.spending_summary("2026-07")

    assert result.total_income == Decimal("23800.00")
    assert result.total_spending == Decimal("9333.20")
    assert result.income_transaction_count == 1
    assert result.spending_transaction_count == 33
    assert result.currency == "CNY"
    raw_debits = [
        item
        for item in MockBankService().list_transactions()
        if item["occurred_at"].startswith("2026-07-")
        and item["direction"] == "DEBIT"
        and item["status"] == "POSTED"
    ]
    assert sum((Decimal(item["amount"]) for item in raw_debits), Decimal(0)) == Decimal(
        "14333.20"
    )
    assert result.total_spending == Decimal("14333.20") - Decimal("5000.00")


def test_valid_statuses_are_explicit_and_non_posted_transactions_are_ignored(
    tmp_path: Path,
) -> None:
    service = write_bank_data(
        tmp_path,
        [
            transaction("posted", "10.10"),
            transaction("pending", "999.99", status="PENDING"),
        ],
    )

    assert VALID_TRANSACTION_STATUSES == frozenset({"POSTED"})
    result = service.spending_summary("2026-08")
    assert result.total_spending == Decimal("10.10")
    assert result.spending_transaction_count == 1


def test_category_breakdown_aggregates_counts_shares_and_order(
    analytics: FinancialAnalyticsService,
) -> None:
    result = analytics.category_breakdown("2026-08")

    assert result.total_spending == Decimal("16547.30")
    assert [item.category for item in result.categories[:4]] == [
        "HOUSING",
        "SHOPPING",
        "TRAVEL",
        "FOOD",
    ]
    food = next(item for item in result.categories if item.category == "FOOD")
    assert food.amount == Decimal("1005.30")
    assert food.transaction_count == 18
    assert food.share == Decimal("1005.30") / Decimal("16547.30")
    assert all(item.category != "TRANSFER" for item in result.categories)


def test_compare_periods_calculates_total_and_category_changes(
    analytics: FinancialAnalyticsService,
) -> None:
    result = analytics.compare_periods("2026-08")

    assert result.current_period == "2026-08"
    assert result.previous_period == "2026-07"
    assert result.current_spending == Decimal("16547.30")
    assert result.previous_spending == Decimal("9333.20")
    assert result.absolute_change == Decimal("7214.10")
    food = next(item for item in result.category_changes if item.category == "FOOD")
    assert food.absolute_change == Decimal("589.10")
    travel = next(item for item in result.category_changes if item.category == "TRAVEL")
    assert travel.previous_amount == Decimal(0)
    assert travel.current_amount == Decimal("4260.00")
    assert travel.percentage_change is None


def test_compare_periods_handles_empty_previous_period_without_division_by_zero(
    analytics: FinancialAnalyticsService,
) -> None:
    result = analytics.compare_periods("2026-06")

    assert result.previous_period == "2026-05"
    assert result.previous_spending == Decimal(0)
    assert result.percentage_change is None
    assert all(item.percentage_change is None for item in result.category_changes)


def test_top_transactions_are_spending_only_and_deterministically_sorted(
    analytics: FinancialAnalyticsService,
) -> None:
    result = analytics.top_transactions("2026-08", limit=5)

    assert [item.transaction_id for item in result.transactions] == [
        "txn_0014",
        "txn_0113",
        "txn_0116",
        "txn_0119",
        "txn_0115",
    ]
    assert [item.amount for item in result.transactions] == sorted(
        (item.amount for item in result.transactions), reverse=True
    )
    assert all(item.category != "TRANSFER" for item in result.transactions)


def test_top_transaction_tie_breaker_uses_time_then_id(tmp_path: Path) -> None:
    service = write_bank_data(
        tmp_path,
        [
            transaction("txn_b", "10.00", occurred_at="2026-08-10T01:00:00Z"),
            transaction("txn_c", "10.00", occurred_at="2026-08-09T01:00:00Z"),
            transaction("txn_a", "10.00", occurred_at="2026-08-09T01:00:00Z"),
        ],
    )

    result = service.top_transactions("2026-08", limit=3)
    assert [item.transaction_id for item in result.transactions] == [
        "txn_a",
        "txn_c",
        "txn_b",
    ]


def test_account_filtering_and_empty_account_ids_mean_all(
    analytics: FinancialAnalyticsService,
) -> None:
    travel = analytics.spending_summary("2026-08", ["acc_travel"])
    all_accounts = analytics.spending_summary("2026-08", [])

    assert travel.total_income == Decimal(0)
    assert travel.total_spending == Decimal("4260.00")
    assert all_accounts == analytics.spending_summary("2026-08")


@pytest.mark.parametrize("month", ["2026-8", "2026-13", "not-a-month", "9999-12"])
def test_invalid_period(month: str, analytics: FinancialAnalyticsService) -> None:
    with pytest.raises(FinancialDomainError) as raised:
        analytics.spending_summary(month)
    assert raised.value.code is FinancialErrorCode.INVALID_PERIOD


def test_unknown_account(analytics: FinancialAnalyticsService) -> None:
    with pytest.raises(FinancialDomainError) as raised:
        analytics.spending_summary("2026-08", ["acc_missing"])
    assert raised.value.code is FinancialErrorCode.ACCOUNT_NOT_FOUND


def test_no_transactions_in_period(analytics: FinancialAnalyticsService) -> None:
    with pytest.raises(FinancialDomainError) as raised:
        analytics.spending_summary("2025-01")
    assert raised.value.code is FinancialErrorCode.NO_TRANSACTIONS_IN_PERIOD


def test_mixed_currency_is_rejected(tmp_path: Path) -> None:
    service = write_bank_data(
        tmp_path,
        [
            transaction("cny", "10.00", account_id="acc_cny"),
            transaction("usd", "10.00", account_id="acc_usd", currency="USD"),
        ],
        account_currencies={"acc_cny": "CNY", "acc_usd": "USD"},
    )

    with pytest.raises(FinancialDomainError) as raised:
        service.spending_summary("2026-08")
    assert raised.value.code is FinancialErrorCode.MIXED_CURRENCY_UNSUPPORTED


def test_decimal_precision_never_uses_binary_float(tmp_path: Path) -> None:
    service = write_bank_data(
        tmp_path,
        [transaction("one", "0.10"), transaction("two", "0.20")],
    )

    result = service.spending_summary("2026-08")
    assert result.total_spending == Decimal("0.30")
    assert isinstance(result.total_spending, Decimal)
