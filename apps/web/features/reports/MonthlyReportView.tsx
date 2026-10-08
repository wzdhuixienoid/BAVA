import type { components } from "@banking/api-client";
import { CategoryBreakdown } from "./CategoryBreakdown";
import { PeriodComparison } from "./PeriodComparison";
import { ReportInsights } from "./ReportInsights";
import { ReportOverview } from "./ReportOverview";
import { TopTransactions } from "./TopTransactions";
import { SpendingReview } from "./SpendingReview";
import { dateTimeLabel, periodLabel } from "./presentation";

type ReportResponse = components["schemas"]["ReportResponse"];

export function MonthlyReportView({ report }: { report: ReportResponse }) {
  const content = report.content;
  const isPartial = content.data_quality.status === "PARTIAL";

  return (
    <article className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-semibold text-cyan-700">{report?.period.length === 4 ? "年度消费报告" : "月度消费报告"}</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight text-slate-950">
            {periodLabel(report.period)}消费报告
          </h1>
          <p className="mt-2 text-sm text-slate-500">生成于 {dateTimeLabel(report.created_at)}</p>
        </div>

      </header>

      {isPartial && (
        <section className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-900">
          <p className="font-semibold">部分分析数据不可用</p>
          {(content.data_quality.notes ?? []).map((note) => (
            <p key={note} className="mt-1 text-sm">{note}</p>
          ))}
        </section>
      )}

      <ReportOverview overview={content.overview} />
      <PeriodComparison comparison={content.period_comparison} currentSpending={content.overview.total_spending_display} />
      <CategoryBreakdown categories={content.category_breakdown} yearly={report.period.length === 4} columns />
      <ReportInsights headline={content.headline} insights={content.insights} />
      <SpendingReview review={content.spending_review} />
      <TopTransactions transactions={content.top_transactions} accountNames={report.account_names} />

      <section className="rounded-xl border border-slate-200 bg-white px-5 py-4 text-sm text-slate-600">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span>数据质量：{isPartial ? "部分数据" : "完整"}</span>
          <span>范围：{content.scope.account_ids.length ? content.scope.account_ids.map((id) => report.account_names?.[id] ?? "账户").join("、") : "全部账户"}</span>
        </div>
      </section>
    </article>
  );
}
