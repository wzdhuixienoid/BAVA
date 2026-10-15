"""Exact, currency-separated statement aggregation before pagination."""

from collections import defaultdict
from decimal import Decimal

from banking_api.domain.statement import (
    StatementCounterpartyTotal,
    StatementCurrencyTotal,
    StatementSummary,
    StatementTransaction,
)
from banking_api.financial.presentation import currency_label
from banking_api.financial.report_formatter import ReportFormatter


def counterparty_label(row) -> str:
    detail = " · ".join(filter(None, (row.counterparty_bank, row.counterparty_account)))
    return f"{row.merchant}（{detail}）" if detail else row.merchant


def build_statement_summary(
    rows, *, is_transfer: bool, scope_display: str, view
) -> StatementSummary:
    formatter = ReportFormatter()
    currency_rows = defaultdict(list)
    grouped = defaultdict(list)
    for row in rows:
        currency_rows[row.currency].append(row)
        identity = row.counterparty_id or f"name:{row.source}:{row.merchant}"
        grouped[(row.currency, row.direction, identity)].append(row)
    totals = []
    direction_totals = {}
    for currency, items in sorted(currency_rows.items()):
        debit = [r for r in items if r.direction == "DEBIT"]
        credit = [r for r in items if r.direction == "CREDIT"]
        spent = sum((r.amount for r in debit), Decimal("0"))
        received = sum((r.amount for r in credit), Decimal("0"))
        direction_totals[(currency, "DEBIT")] = spent
        direction_totals[(currency, "CREDIT")] = received
        totals.append(
            StatementCurrencyTotal(
                currency=currency,
                debit_count=len(debit),
                credit_count=len(credit),
                total_debit=spent,
                total_credit=received,
                debit_display=formatter.money(spent, currency),
                credit_display=formatter.money(received, currency),
            )
        )
    groups = []
    for (currency, direction, identity), items in grouped.items():
        amount = sum((r.amount for r in items), Decimal("0"))
        groups.append(
            StatementCounterpartyTotal(
                counterparty_key=identity,
                display_name=counterparty_label(items[0]),
                identity_known=items[0].counterparty_id is not None,
                direction=direction,
                currency=currency,
                transaction_count=len(items),
                amount=amount,
                amount_display=formatter.money(amount, currency),
                share_display=formatter.ratio(amount / direction_totals[(currency, direction)]),
            )
        )
    groups.sort(key=lambda g: (g.currency, g.direction != "DEBIT", -g.amount, g.counterparty_key))
    insights = []
    for total in totals:
        outgoing = [g for g in groups if g.currency == total.currency and g.direction == "DEBIT"]
        if outgoing:
            top = outgoing[0]
            target = "收款人" if is_transfer and top.identity_known else "账单对手方"
            rank = "并列最高的" if sum(g.amount == top.amount for g in outgoing) > 1 else "最高的"
            insights.append(
                f"{currency_label(total.currency)}的{'转出' if is_transfer else '支出'}中，"
                f"金额{rank}{target}是"
                f"{top.display_name}：共{top.transaction_count}笔、{top.amount_display}，"
                f"占该币种{'转出' if is_transfer else '支出'}金额的{top.share_display}。"
            )
    latest: StatementTransaction | None = view(rows[0]) if rows else None
    if latest:
        action = (
            ("转出" if latest.direction == "DEBIT" else "转入")
            if is_transfer
            else ("支出" if latest.direction == "DEBIT" else "收入")
        )
        insights.append(
            f"所查范围内最近一笔发生在{latest.occurred_at_display}，"
            f"{counterparty_label(latest)}，"
            f"{action}{formatter.money(latest.amount, latest.currency)}，"
            f"记入{latest.account_display}。"
        )
    unidentified = any(not g.identity_known for g in groups)
    return StatementSummary(
        is_transfer=is_transfer,
        scope_display=scope_display,
        totals=totals,
        counterparties=groups[:20],
        counterparty_group_count=len(groups),
        latest_transaction=latest,
        insights=insights,
        grouping_note="未提供唯一对手方标识的流水按账单名称归集，不代表同一自然人。"
        if is_transfer and unidentified
        else None,
    )
