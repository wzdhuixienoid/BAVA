"""Render only typed bank facts; never calculate totals from the visible page."""

import re

from banking_api.domain.statement import AccountStatementResult
from banking_api.financial.presentation import currency_label, transaction_time


def md(value: str) -> str:
    return re.sub(r"([\\`*_{}\[\]<>|])", r"\\\1", value.replace("\n", " "))


def render_statement(page: AccountStatementResult) -> str:
    summary = page.summary
    heading = "转账" if summary and summary.is_transfer else "账单"
    out_label, in_label = ("转出", "转入") if summary and summary.is_transfer else ("支出", "收入")
    parts = [
        f"**分析区间：{transaction_time(page.start_at)} 至 {transaction_time(page.end_at)}"
        "（北京时间，终点不含）**",
    ]
    if summary:
        parts.append(md(summary.scope_display))
        if page.total_count:
            parts.append(f"## {heading}总览")
            table = [
                f"| 币种 | {out_label}金额 / 笔数 | {in_label}金额 / 笔数 |",
                "| --- | ---: | ---: |",
            ]
            table += [
                f"| {md(currency_label(t.currency))} | {md(t.debit_display)} / {t.debit_count}笔 | "
                f"{md(t.credit_display)} / {t.credit_count}笔 |"
                for t in summary.totals
            ]
            parts.append("\n".join(table))
            parts.append(
                f"所选范围共 **{page.total_count}笔**已入账{heading}，汇总覆盖全部匹配记录。"
            )
            parts.append(
                "## 按收款人／付款方汇总" if summary.is_transfer else "## 按商户／对手方汇总"
            )
            table = [
                "| 收款人／付款方 | 方向 | 币种 | 金额 | 笔数 | 占同方向金额 |",
                "| --- | --- | --- | ---: | ---: | ---: |",
            ]
            for group in summary.counterparties:
                direction = out_label if group.direction == "DEBIT" else in_label
                table.append(
                    f"| {md(group.display_name)} | {direction} | "
                    f"{md(currency_label(group.currency))} | {md(group.amount_display)} | "
                    f"{group.transaction_count} | {group.share_display} |"
                )
            parts.append("\n".join(table))
            if summary.counterparty_group_count > len(summary.counterparties):
                parts.append("此处展示前20个对手方分组，其余记录仍包含在总额中。")
            if summary.grouping_note:
                parts.append(summary.grouping_note)
            parts += ["## 解读", "\n".join(f"- {md(text)}" for text in summary.insights)]
    if page.transactions:
        parts.append(f"## 最近{heading}明细" if page.offset == 0 else f"## {heading}明细（续页）")
        table = [
            "| 时间（北京时间） | 对手方 | 账户 | 金额 |",
            "| --- | --- | --- | ---: |",
        ]
        table += [
            f"| {r.occurred_at_display} | {md(r.merchant)} | {md(r.account_display)} | "
            f"{md(r.amount_display)} {md(currency_label(r.currency))} |"
            for r in page.transactions
        ]
        parts.append("\n".join(table))
        if page.next_offset is not None:
            parts.append(
                f"当前展示第{page.offset + 1}–{page.offset + len(page.transactions)}条，"
                f"共{page.total_count}条。"
                "输入“下一页”可继续查看；上方汇总不受分页影响。"
            )
    else:
        parts.append(
            "所选期间和筛选条件下没有已入账记录。"
            if page.total_count == 0
            else "已到最后一页，没有更多记录。"
        )
    parts.append(page.posting_scope)
    return "\n\n".join(parts)
