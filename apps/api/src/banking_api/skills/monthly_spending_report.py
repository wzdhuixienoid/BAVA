from banking_api.agent_skills import packaged_catalog
from banking_api.financial.analysis_snapshot import FinancialAnalysisSnapshot
from banking_api.financial.report_formatter import ReportFormatter
from banking_api.financial.report_models import (
    DataQualityStatus,
    MonthlySpendingReport,
    MonthlySpendingReportCore,
    ReportCategory,
    ReportDataQuality,
    ReportOverview,
    ReportPeriodComparison,
    ReportScope,
    ReportTopTransaction,
)
from banking_api.skills.models import SkillDefinition

MONTHLY_SPENDING_REPORT_SKILL_ID = "skill:monthly-spending-report"


class ReportInputError(Exception):
    pass


class MonthlySpendingReportSkill:
    definition = SkillDefinition(
        skill_id=MONTHLY_SPENDING_REPORT_SKILL_ID,
        agent_skill_name="monthly-spending-report",
        version=1,
        description="将已验证的金融分析快照组织为数值可信的月度消费报告。",
        input_schema=FinancialAnalysisSnapshot,
        output_schema=MonthlySpendingReport,
        allowed_tools=(),
    )

    def __init__(self, formatter: ReportFormatter | None = None) -> None:
        self.active_skill = packaged_catalog().bind_business_skill(self.definition)
        self.formatter = formatter or ReportFormatter()

    def build_core(self, snapshot: FinancialAnalysisSnapshot) -> MonthlySpendingReportCore:
        self._validate_input(snapshot)
        summary = snapshot.spending_summary
        breakdown = snapshot.category_breakdown
        if summary is None or breakdown is None or snapshot.period is None:
            raise ReportInputError("Snapshot is missing required report data")

        comparison = snapshot.period_comparison
        comparison_by_category = (
            {item.category: item for item in comparison.category_changes}
            if comparison is not None
            else {}
        )
        categories: list[ReportCategory] = []
        for item in breakdown.categories:
            change = comparison_by_category.get(item.category)
            categories.append(
                ReportCategory(
                    category=item.category,
                    amount=item.amount,
                    amount_display=self.formatter.money(item.amount, summary.currency),
                    transaction_count=item.transaction_count,
                    share=item.share,
                    share_display=self.formatter.ratio(item.share),
                    previous_amount=change.previous_amount if change else None,
                    previous_amount_display=(
                        self.formatter.money(change.previous_amount, summary.currency)
                        if change
                        else None
                    ),
                    absolute_change=change.absolute_change if change else None,
                    absolute_change_display=(
                        self.formatter.money_change(
                            change.absolute_change,
                            summary.currency,
                        )
                        if change
                        else None
                    ),
                    percentage_change=change.percentage_change if change else None,
                    percentage_change_display=(
                        self.formatter.percentage_change(change.percentage_change)
                        if change
                        else None
                    ),
                )
            )

        report_comparison = None
        if comparison is not None:
            report_comparison = ReportPeriodComparison(
                previous_period=comparison.previous_period,
                previous_spending=comparison.previous_spending,
                previous_spending_display=self.formatter.money(
                    comparison.previous_spending,
                    summary.currency,
                ),
                absolute_change=comparison.absolute_change,
                absolute_change_display=self.formatter.money_change(
                    comparison.absolute_change,
                    summary.currency,
                ),
                percentage_change=comparison.percentage_change,
                percentage_change_display=self.formatter.percentage_change(
                    comparison.percentage_change
                ),
            )

        top_transactions = [
            ReportTopTransaction(
                transaction_id=item.transaction_id,
                merchant=item.merchant,
                description=item.description,
                category=item.category,
                amount=item.amount,
                amount_display=self.formatter.money(item.amount, summary.currency),
                occurred_at=item.occurred_at,
                account_id=item.account_id,
            )
            for item in (
                snapshot.top_transactions.transactions
                if snapshot.top_transactions is not None
                else []
            )
        ]
        notes: list[str] = []
        if comparison is None:
            notes.append("未提供上一期比较数据。")
        if snapshot.top_transactions is None:
            notes.append("未提供主要交易数据。")

        return MonthlySpendingReportCore(
            spending_review=summary.spending_review,
            period=snapshot.period,
            scope=ReportScope(account_ids=list(snapshot.account_ids)),
            overview=ReportOverview(
                total_income=summary.total_income,
                total_income_display=self.formatter.money(
                    summary.total_income,
                    summary.currency,
                ),
                total_spending=summary.total_spending,
                total_spending_display=self.formatter.money(
                    summary.total_spending,
                    summary.currency,
                ),
                transaction_count=summary.spending_transaction_count,
                currency=summary.currency,
            ),
            period_comparison=report_comparison,
            category_breakdown=categories,
            top_transactions=top_transactions,
            data_quality=ReportDataQuality(
                status=(DataQualityStatus.COMPLETE if not notes else DataQualityStatus.PARTIAL),
                notes=notes,
            ),
        )

    @staticmethod
    def _validate_input(snapshot: FinancialAnalysisSnapshot) -> None:
        if not isinstance(snapshot, FinancialAnalysisSnapshot):
            raise ReportInputError("Input must be a FinancialAnalysisSnapshot")
        if snapshot.period is None or snapshot.spending_summary is None:
            raise ReportInputError("Snapshot is missing period or spending summary")
        if snapshot.category_breakdown is None:
            raise ReportInputError("Snapshot is missing category breakdown")
        evidence_capabilities = {item.capability_id for item in snapshot.tool_evidence}
        required = {
            "transaction.spending_summary",
            "transaction.category_breakdown",
        }
        if not required.issubset(evidence_capabilities):
            raise ReportInputError("Snapshot is missing required tool evidence")
        if (
            snapshot.period_comparison is not None
            and "transaction.compare_periods" not in evidence_capabilities
        ):
            raise ReportInputError("Snapshot comparison has no tool evidence")
        if (
            snapshot.top_transactions is not None
            and "transaction.top_transactions" not in evidence_capabilities
        ):
            raise ReportInputError("Snapshot top transactions have no tool evidence")

        summary = snapshot.spending_summary
        breakdown = snapshot.category_breakdown
        if summary.period != snapshot.period or breakdown.period != snapshot.period:
            raise ReportInputError("Snapshot periods are inconsistent")
        if summary.currency != breakdown.currency:
            raise ReportInputError("Snapshot currencies are inconsistent")
        if summary.total_spending != breakdown.total_spending:
            raise ReportInputError("Snapshot spending totals are inconsistent")

        comparison = snapshot.period_comparison
        if comparison is not None:
            if comparison.current_period != snapshot.period:
                raise ReportInputError("Comparison period is inconsistent")
            if comparison.currency != summary.currency:
                raise ReportInputError("Comparison currency is inconsistent")
            if comparison.current_spending != summary.total_spending:
                raise ReportInputError("Comparison spending total is inconsistent")
            changes = {item.category: item for item in comparison.category_changes}
            for category in breakdown.categories:
                change = changes.get(category.category)
                if change is None or change.current_amount != category.amount:
                    raise ReportInputError("Category comparison is inconsistent")

        top = snapshot.top_transactions
        if top is not None:
            if top.period != snapshot.period or top.currency != summary.currency:
                raise ReportInputError("Top transaction scope is inconsistent")
            if snapshot.account_ids and any(
                item.account_id not in snapshot.account_ids for item in top.transactions
            ):
                raise ReportInputError("Top transaction account is outside report scope")
