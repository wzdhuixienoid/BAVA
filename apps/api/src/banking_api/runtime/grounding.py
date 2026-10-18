"""Client-visible banking facts are rendered exclusively from this run's typed evidence."""

from datetime import datetime

from banking_api.agents.models import AgentDefinition
from banking_api.financial.analysis_snapshot import build_financial_analysis_snapshot
from banking_api.financial.presentation import category_label, transaction_time
from banking_api.financial.report_formatter import ReportFormatter
from banking_api.runtime.base import SuccessfulToolResult

NO_VERIFIED_FACTS = (
    "尚未取得本次查询的银行数据，无法确认余额、账单或交易结果。请明确查询对象后重试。"
)


def _period(value: str) -> str:
    if "/" in value:
        try:
            start, end = value.split("/", 1)
            return (
                f"{transaction_time(datetime.fromisoformat(start))} 至 "
                f"{transaction_time(datetime.fromisoformat(end))}"
            )
        except ValueError:
            return value
    return value


def ground_read_answer(
    agent: AgentDefinition, request: str, answer: str, results: list[SuccessfulToolResult]
) -> str:
    """Keep wealth's separate validated answer contract; bank readers never publish model prose.

    This is deliberately an evidence renderer, not a regex detector of possibly false claims.
    A tool loop's completion is never evidence that money has moved.
    """
    if agent.agent_id not in {"agent:personal-banking", "agent:subscription-analysis"}:
        return answer
    if not results:
        if request.strip().rstrip("！!。") in {"你好", "您好", "hello", "hi"}:
            return "你好，我可以帮你查询账户、分析账单、管理订阅和办理业务。"
        return NO_VERIFIED_FACTS

    from banking_api.application.account_results import account_query_answer
    from banking_api.application.statement_results import statement_answer

    sections = [account_query_answer(results), statement_answer(results)]
    fmt = ReportFormatter()
    snapshot = build_financial_analysis_snapshot(results)
    if summary := snapshot.spending_summary:
        sections.append(
            f"查询期间：{_period(summary.period)}。\n"
            f"消费支出：{fmt.money(summary.total_spending, summary.currency)}"
            f"（{summary.spending_transaction_count} 笔）；"
            f"收入：{fmt.money(summary.total_income, summary.currency)}"
            f"（{summary.income_transaction_count} 笔）。"
        )
    if breakdown := snapshot.category_breakdown:
        sections.append(
            "消费分类：\n"
            + "\n".join(
                f"- {category_label(item.category)}：{fmt.money(item.amount, breakdown.currency)}"
                f"，占比 {item.share_display}，{item.transaction_count} 笔"
                for item in breakdown.categories
            )
        )
    if comparison := snapshot.period_comparison:
        sections.append(
            f"与 {_period(comparison.previous_period)} 相比，消费变化"
            f" {fmt.money_change(comparison.absolute_change, comparison.currency)}"
            f"（{fmt.percentage_change(comparison.percentage_change)}）。"
        )
    if top := snapshot.top_transactions:
        sections.append(
            "主要消费明细：\n"
            + "\n".join(
                f"- {item.occurred_at_display} · {item.merchant} · "
                f"{fmt.money(item.amount, item.currency)} · {item.category_display}"
                for item in top.transactions
            )
        )
    for result in results:
        if result.capability_id in {"payee.list", "payee.search"}:
            from banking_api.tools.models import ListPayeesOutput

            payees = ListPayeesOutput.model_validate(result.output).payees
            sections.append(
                "收款人：\n"
                + "\n".join(
                    f"- {p.display_name} · {p.bank_name} · {p.masked_account}" for p in payees
                )
                if payees
                else "未找到匹配的收款人。"
            )
        if result.capability_id == "subscription.analyze":
            from banking_api.subscriptions.models import SubscriptionListOutput

            data = SubscriptionListOutput.model_validate(result.output).snapshot
            sections.append(
                "订阅费用：\n"
                + "\n".join(
                    f"- 每月 {item.amount_display}" for item in data.monthly_cost_by_currency
                )
            )
            sections.append(
                "\n".join(
                    f"- {s.merchant}：{s.last_charge_display}，"
                    f"{'已取消' if s.status.value == 'CANCELLED' else '有效'}"
                    for s in data.subscriptions
                )
                or "当前未发现周期订阅。"
            )
        if result.capability_id == "transaction.detect_anomalies":
            from banking_api.financial.anomaly_models import TransactionAnomalySnapshot
            from banking_api.skills.transaction_anomaly_analysis import (
                TransactionAnomalyAnalysisSkill,
            )

            data = TransactionAnomalySnapshot.model_validate(result.output["snapshot"])
            sections.append(TransactionAnomalyAnalysisSkill().execute(data).answer)
    if (
        summary
        and summary.spending_review
        and not any(r.capability_id == "transaction.detect_anomalies" for r in results)
    ):
        sections.append(summary.spending_review.answer)
    if "余额" in request and not any(r.capability_id == "account.get_balance" for r in results):
        sections.append("尚未取得本次余额数据，以上结果不能用于判断可用余额。")
    return "\n\n".join(section for section in sections if section) or NO_VERIFIED_FACTS
