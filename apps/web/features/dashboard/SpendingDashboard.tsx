import type { components } from "@banking/api-client";
import { ReportOverview } from "@/features/reports/ReportOverview";
import { PeriodComparison } from "@/features/reports/PeriodComparison";
import { CategoryBreakdown } from "@/features/reports/CategoryBreakdown";
import { TopTransactions } from "@/features/reports/TopTransactions";
import { periodLabel } from "@/features/reports/presentation";

export function SpendingDashboard({ spending }: { spending: components["schemas"]["MonthlySpendingReportCore"] }) {
  return <section aria-label="消费 Dashboard" className="min-w-0 space-y-4">
    <h2 className="text-lg font-semibold text-slate-950">{periodLabel(spending.period)}消费总览</h2>
    <ReportOverview overview={spending.overview} />
    <PeriodComparison comparison={spending.period_comparison} />
    <CategoryBreakdown categories={spending.category_breakdown} />
    <TopTransactions transactions={spending.top_transactions} />
  </section>;
}
