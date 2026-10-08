import type { components } from "@banking/api-client";
import { periodLabel } from "./presentation";

type Comparison = components["schemas"]["ReportPeriodComparison"];

export function PeriodComparison({ comparison, currentSpending }: { comparison: Comparison | null; currentSpending?: string }) {
  const previousLabel = comparison?.previous_period.length === 4 ? "上年" : "上月";
  return <section aria-label="支出变化" className="rounded-2xl border border-slate-200 bg-white px-6 py-5 shadow-sm">
    <div className="grid items-center gap-5 sm:grid-cols-2 lg:grid-cols-4">
      <div>
        <h2 className="text-base font-semibold text-slate-950">较{previousLabel}</h2>
        <p className="mt-1 text-xs text-slate-500">{comparison ? `对比 ${periodLabel(comparison.previous_period)}` : "未提供上一期比较数据"}</p>
      </div>
      {currentSpending && <div className="sm:border-l sm:border-slate-100 sm:pl-5">
        <p className="text-xs text-slate-500">本期支出</p>
        <p className="mt-1 text-lg font-semibold tabular-nums text-slate-900">{currentSpending}</p>
      </div>}
      {comparison && <div className="sm:border-l sm:border-slate-100 sm:pl-5">
        <p className="text-xs text-slate-500">{previousLabel}支出</p>
        <p className="mt-1 text-lg font-semibold tabular-nums text-slate-900">{comparison.previous_spending_display}</p>
      </div>}
      <div className="flex items-center gap-3 sm:justify-end lg:border-l lg:border-slate-100 lg:pl-5">
        <p className="text-xl font-semibold tabular-nums text-slate-950">{comparison?.absolute_change_display ?? "—"}</p>
        <p className="rounded-full bg-cyan-50 px-2 py-1 text-xs font-semibold text-cyan-700">{comparison?.percentage_change_display ?? "—"}</p>
      </div>
    </div>
  </section>;
}
