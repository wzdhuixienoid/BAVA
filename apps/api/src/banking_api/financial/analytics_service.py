import re
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import Any

from banking_api.financial.errors import FinancialDomainError, FinancialErrorCode
from banking_api.financial.models import (
    CategoryBreakdown,
    CategoryChange,
    CategorySpending,
    SpendingPeriodComparison,
    SpendingSummary,
    TopTransaction,
    TopTransactions,
)
from banking_api.mock_bank.service import MockBankService

VALID_TRANSACTION_STATUSES = frozenset({"POSTED"})
TRANSFER_CATEGORY = "TRANSFER"
_PERIOD_PATTERN = re.compile(r"^(\d{4})-(\d{2})$")
_ZERO = Decimal("0")


class FinancialAnalyticsService:
    """Deterministic Decimal-based analytics over committed synthetic transactions."""

    def __init__(self, bank: MockBankService) -> None:
        self._bank = bank

    def spending_summary(
        self, month: str, account_ids: list[str] | None = None, *, user_id: str
    ) -> SpendingSummary:
        transactions = self._period_transactions(month, account_ids, user_id=user_id)
        currency = self._single_currency(transactions)
        income = [
            item
            for item in transactions
            if item["direction"] == "CREDIT" and item["category"] != TRANSFER_CATEGORY
        ]
        spending = [item for item in transactions if self._is_spending(item)]
        return SpendingSummary(
            period=month,
            total_income=self._sum_amounts(income),
            total_spending=self._sum_amounts(spending),
            income_transaction_count=len(income),
            spending_transaction_count=len(spending),
            currency=currency,
        )

    def category_breakdown(
        self, month: str, account_ids: list[str] | None = None, *, user_id: str
    ) -> CategoryBreakdown:
        transactions = self._period_transactions(month, account_ids, user_id=user_id)
        currency = self._single_currency(transactions)
        spending = [item for item in transactions if self._is_spending(item)]
        total = self._sum_amounts(spending)
        amounts: dict[str, Decimal] = defaultdict(lambda: _ZERO)
        counts: dict[str, int] = defaultdict(int)
        for item in spending:
            category = str(item["category"])
            amounts[category] += self._amount(item)
            counts[category] += 1
        ordered = sorted(amounts, key=lambda category: (-amounts[category], category))
        return CategoryBreakdown(
            period=month,
            total_spending=total,
            currency=currency,
            categories=[
                CategorySpending(
                    category=category,
                    amount=amounts[category],
                    transaction_count=counts[category],
                    share=self._ratio(amounts[category], total),
                )
                for category in ordered
            ],
        )

    def compare_periods(
        self, month: str, account_ids: list[str] | None = None, *, user_id: str
    ) -> SpendingPeriodComparison:
        current_start, _ = self._period_bounds(month)
        previous_month = self._previous_month(current_start)
        current = self._period_transactions(month, account_ids, user_id=user_id)
        previous = self._period_transactions(
            previous_month,
            account_ids,
            user_id=user_id,
            allow_empty=True,
        )
        currency = self._single_currency([*current, *previous])
        current_categories = self._category_amounts(current)
        previous_categories = self._category_amounts(previous)
        current_total = sum(current_categories.values(), _ZERO)
        previous_total = sum(previous_categories.values(), _ZERO)
        categories = sorted(set(current_categories) | set(previous_categories))
        return SpendingPeriodComparison(
            current_period=month,
            previous_period=previous_month,
            current_spending=current_total,
            previous_spending=previous_total,
            absolute_change=current_total - previous_total,
            percentage_change=self._percentage_change(current_total, previous_total),
            currency=currency,
            category_changes=[
                self._category_change(
                    category,
                    current_categories.get(category, _ZERO),
                    previous_categories.get(category, _ZERO),
                )
                for category in categories
            ],
        )

    def top_transactions(
        self,
        month: str,
        limit: int = 5,
        account_ids: list[str] | None = None,
        *,
        user_id: str,
    ) -> TopTransactions:
        if not 1 <= limit <= 20:
            raise ValueError("limit must be between 1 and 20")
        transactions = self._period_transactions(month, account_ids, user_id=user_id)
        currency = self._single_currency(transactions)
        spending = [item for item in transactions if self._is_spending(item)]
        ordered = sorted(
            spending,
            key=lambda item: (
                -self._amount(item),
                self._occurred_at(item),
                str(item["transaction_id"]),
            ),
        )
        return TopTransactions(
            period=month,
            currency=currency,
            transactions=[
                TopTransaction(
                    transaction_id=str(item["transaction_id"]),
                    occurred_at=self._occurred_at(item),
                    merchant=str(item["merchant"]),
                    description=str(item["description"]),
                    category=str(item["category"]),
                    amount=self._amount(item),
                    currency=str(item["currency"]),
                    account_id=str(item["account_id"]),
                )
                for item in ordered[:limit]
            ],
        )

    def _period_transactions(
        self,
        month: str,
        account_ids: list[str] | None,
        *,
        user_id: str,
        allow_empty: bool = False,
    ) -> list[dict[str, Any]]:
        start, end = self._period_bounds(month)
        selected_accounts = self._selected_account_ids(account_ids, user_id=user_id)
        transactions = [
            item
            for item in self._bank.list_transactions(user_id=user_id)
            if str(item.get("status")) in VALID_TRANSACTION_STATUSES
            and str(item.get("account_id")) in selected_accounts
            and start <= self._occurred_at(item) < end
        ]
        if not transactions and not allow_empty:
            raise FinancialDomainError(
                FinancialErrorCode.NO_TRANSACTIONS_IN_PERIOD,
                f"No transactions found in period: {month}",
            )
        return transactions

    def _selected_account_ids(
        self, account_ids: list[str] | None, *, user_id: str
    ) -> frozenset[str]:
        known = {str(item["account_id"]) for item in self._bank.list_accounts(user_id=user_id)}
        if not account_ids:
            return frozenset(known)
        requested = frozenset(account_ids)
        unknown = sorted(requested - known)
        if unknown:
            raise FinancialDomainError(
                FinancialErrorCode.ACCOUNT_NOT_FOUND,
                f"Account not found: {unknown[0]}",
            )
        return requested

    @staticmethod
    def _period_bounds(month: str) -> tuple[datetime, datetime]:
        match = _PERIOD_PATTERN.fullmatch(month)
        if match is None:
            raise FinancialDomainError(
                FinancialErrorCode.INVALID_PERIOD,
                f"Invalid period: {month}",
            )
        year, month_number = (int(part) for part in match.groups())
        try:
            start = datetime(year, month_number, 1, tzinfo=UTC)
            if month_number == 12:
                end = datetime(year + 1, 1, 1, tzinfo=UTC)
            else:
                end = datetime(year, month_number + 1, 1, tzinfo=UTC)
        except ValueError as exc:
            raise FinancialDomainError(
                FinancialErrorCode.INVALID_PERIOD,
                f"Invalid period: {month}",
            ) from exc
        return start, end

    @staticmethod
    def _previous_month(start: datetime) -> str:
        if start.month == 1:
            return f"{start.year - 1:04d}-12"
        return f"{start.year:04d}-{start.month - 1:02d}"

    @staticmethod
    def _occurred_at(item: dict[str, Any]) -> datetime:
        value = str(item["occurred_at"])
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @staticmethod
    def _amount(item: dict[str, Any]) -> Decimal:
        amount = Decimal(str(item["amount"]))
        if amount < _ZERO:
            raise ValueError("Transaction amounts must be non-negative")
        return amount

    @classmethod
    def _sum_amounts(cls, transactions: list[dict[str, Any]]) -> Decimal:
        return sum((cls._amount(item) for item in transactions), _ZERO)

    @staticmethod
    def _is_spending(item: dict[str, Any]) -> bool:
        return item["direction"] == "DEBIT" and item["category"] != TRANSFER_CATEGORY

    @classmethod
    def _category_amounts(cls, transactions: list[dict[str, Any]]) -> dict[str, Decimal]:
        amounts: dict[str, Decimal] = defaultdict(lambda: _ZERO)
        for item in transactions:
            if cls._is_spending(item):
                amounts[str(item["category"])] += cls._amount(item)
        return dict(amounts)

    @staticmethod
    def _single_currency(transactions: list[dict[str, Any]]) -> str:
        currencies = {str(item["currency"]) for item in transactions}
        if len(currencies) > 1:
            raise FinancialDomainError(
                FinancialErrorCode.MIXED_CURRENCY_UNSUPPORTED,
                "Cannot aggregate transactions with different currencies",
            )
        if not currencies:
            raise FinancialDomainError(
                FinancialErrorCode.NO_TRANSACTIONS_IN_PERIOD,
                "No transactions available to determine currency",
            )
        return next(iter(currencies))

    @staticmethod
    def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
        if denominator == _ZERO:
            return _ZERO
        with localcontext() as context:
            context.prec = 28
            return numerator / denominator

    @classmethod
    def _percentage_change(cls, current: Decimal, previous: Decimal) -> Decimal | None:
        if previous == _ZERO:
            return None
        with localcontext() as context:
            context.prec = 28
            return (current - previous) / previous * Decimal("100")

    @classmethod
    def _category_change(cls, category: str, current: Decimal, previous: Decimal) -> CategoryChange:
        return CategoryChange(
            category=category,
            current_amount=current,
            previous_amount=previous,
            absolute_change=current - previous,
            percentage_change=cls._percentage_change(current, previous),
        )
