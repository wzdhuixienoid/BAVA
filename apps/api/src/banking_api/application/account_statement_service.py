"""Read-only account statement over posted bank and persisted payment cash movements."""

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select

from banking_api.domain.dashboard import DashboardTransaction, DashboardTransactionPage
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.financial.report_formatter import ReportFormatter
from banking_api.persistence.models import MockBankTransferModel, MockSubscriptionChargeModel
from banking_api.wealth.models import WealthLedger, WealthOrder

BEIJING = ZoneInfo("Asia/Shanghai")
CASH_ACTIONS = {
    "PURCHASE_DEBIT": ("DEBIT", "WEALTH", "理财申购 · 已入账"),
    "REDEEM_CREDIT": ("CREDIT", "WEALTH", "理财赎回到账"),
    "REFUND": ("CREDIT", "REFUND", "理财申购余款退款 · 已入账"),
}


def utc(value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


class AccountStatementService:
    def __init__(self, bank, session):
        self.bank = bank
        self.session = session

    async def posted_transactions(self, *, user_id, as_of) -> list[DashboardTransaction]:
        accounts = {a["account_id"] for a in self.bank.list_accounts(user_id=user_id)}
        rows = []
        cutoff = utc(as_of)

        def add(
            identity,
            merchant,
            description,
            category,
            amount,
            currency,
            when,
            account,
            direction,
            source,
        ):
            if account not in accounts:
                return
            when = utc(when)
            amount = Decimal(str(amount))
            if when > cutoff or amount <= 0:
                return
            rows.append(
                DashboardTransaction(
                    transaction_id=identity,
                    merchant=merchant,
                    description=description,
                    category=category,
                    amount=amount,
                    currency=currency,
                    occurred_at=when,
                    account_id=account,
                    direction=direction,
                    source=source,
                    amount_display=("+" if direction == "CREDIT" else "-")
                    + ReportFormatter().money(amount, currency),
                )
            )

        for row in self.bank.list_transactions(user_id=user_id):
            if row.get("status") != "POSTED" or row.get("direction") not in {"DEBIT", "CREDIT"}:
                continue
            add(
                str(row["transaction_id"]),
                row["merchant"],
                row.get("description", ""),
                row["category"],
                row["amount"],
                row["currency"],
                row["occurred_at"],
                row.get("account_id"),
                row["direction"],
                "BANK",
            )

        charges = await self.session.scalars(
            select(MockSubscriptionChargeModel).where(
                MockSubscriptionChargeModel.user_id == user_id,
                MockSubscriptionChargeModel.status == "SUCCEEDED",
                MockSubscriptionChargeModel.created_at <= cutoff,
            )
        )
        for row in charges:
            add(
                f"subscription:{row.charge_id}",
                row.merchant,
                "订阅续费 · 已入账",
                "SUBSCRIPTION",
                row.amount,
                row.currency,
                row.created_at,
                row.source_account_id,
                "DEBIT",
                "SUBSCRIPTION",
            )

        movements = await self.session.execute(
            select(WealthLedger, WealthOrder)
            .join(
                WealthOrder,
                WealthOrder.order_id == WealthLedger.order_id,
            )
            .where(
                WealthLedger.user_id == user_id,
                WealthOrder.user_id == user_id,
                WealthLedger.account_id == WealthOrder.account_id,
                WealthLedger.action.in_(CASH_ACTIONS),
                WealthLedger.amount > 0,
                WealthLedger.created_at <= cutoff,
            )
        )
        for ledger, order in movements:
            direction, cash_category, description = CASH_ACTIONS[ledger.action]
            add(
                f"wealth:{ledger.ledger_id}",
                order.snapshot["name"],
                description,
                cash_category,
                ledger.amount,
                order.snapshot.get("currency", "CNY"),
                ledger.created_at,
                ledger.account_id,
                direction,
                "WEALTH",
            )

        payees = {p["payee_id"]: p["display_name"] for p in self.bank.list_payees(user_id=user_id)}
        transfers = await self.session.scalars(
            select(MockBankTransferModel).where(
                MockBankTransferModel.status == "SUCCEEDED",
                or_(
                    MockBankTransferModel.user_id == user_id,
                    MockBankTransferModel.destination_user_id == user_id,
                ),
            )
        )
        for row in transfers:
            if row.user_id == user_id:
                add(
                    f"transfer:{row.provider_reference}:debit",
                    payees.get(row.payee_id, "转账支出"),
                    row.remark or "转账支出 · 已入账",
                    "TRANSFER",
                    row.amount,
                    row.currency,
                    row.applied_at or row.created_at,
                    row.source_account_id,
                    "DEBIT",
                    "TRANSFER",
                )
            if row.destination_user_id == user_id and row.credited_at is not None:
                add(
                    f"transfer:{row.provider_reference}:credit",
                    "转账收入",
                    row.remark or "转账收入 · 已入账",
                    "TRANSFER",
                    row.amount,
                    row.currency,
                    row.credited_at,
                    row.destination_account_id,
                    "CREDIT",
                    "TRANSFER",
                )

        rows.sort(key=lambda row: (row.occurred_at, row.transaction_id), reverse=True)
        return rows

    async def page(
        self,
        *,
        user_id,
        as_of,
        month=None,
        year=None,
        month_number=None,
        category=None,
        account_id=None,
        offset=0,
        limit=100,
    ) -> DashboardTransactionPage:
        analytics = FinancialAnalyticsService(self.bank)
        if month:
            analytics._period_bounds(month)
        if account_id:
            analytics._selected_account_ids([account_id], user_id=user_id)
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid statement pagination")
        rows = await self.posted_transactions(user_id=user_id, as_of=as_of)
        filtered = [
            row
            for row in rows
            if (not month or row.occurred_at.astimezone(BEIJING).strftime("%Y-%m") == month)
            and (year is None or row.occurred_at.astimezone(BEIJING).year == year)
            and (month_number is None or row.occurred_at.astimezone(BEIJING).month == month_number)
            and (not category or row.category == category)
            and (not account_id or row.account_id == account_id)
        ]
        return DashboardTransactionPage(
            transactions=filtered[offset : offset + limit],
            total_count=len(filtered),
            offset=offset,
            available_months=sorted(
                {row.occurred_at.astimezone(BEIJING).strftime("%Y-%m") for row in rows},
                reverse=True,
            ),
            available_categories=sorted({row.category for row in rows}),
        )


class PostedAnalysisBank:
    """Principal-scoped analytical view; investments are asset movements, not consumption."""

    def __init__(self, bank, user_id, rows):
        self.bank, self.user_id = bank, user_id
        self.rows = rows

    def list_accounts(self, *, user_id):
        return self.bank.list_accounts(user_id=user_id) if user_id == self.user_id else []

    def list_transactions(self, *, user_id):
        if user_id != self.user_id:
            return []
        return [
            {
                "transaction_id": row.transaction_id,
                "merchant": row.merchant,
                "description": row.description,
                "account_id": row.account_id,
                "category": row.category,
                "amount": str(row.amount),
                "currency": row.currency,
                "occurred_at": row.occurred_at.isoformat(),
                "direction": row.direction,
                "status": "POSTED",
            }
            for row in self.rows
            if row.source != "WEALTH"
        ]
