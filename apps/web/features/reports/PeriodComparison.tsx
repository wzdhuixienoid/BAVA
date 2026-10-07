import type { components } from "@banking/api-client";
import { periodLabel } from "./presentation";

type Comparison = components["schemas"]["ReportPeriodComparison"];

export function PeriodComparison({ comparison }: { comparison: Comparison | null }) {
  const previousLabel = comparison?.previous_period.length === 4 ? "上年" : "上月";
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">较{previousLabel}</h2>
          <p className="mt-1 text-sm text-slate-500">
            {comparison ? `对比 ${periodLabel(comparison.previous_period)}` : "未提供上一期比较数据"}
          </p>
        </div>
        <div className="text-right">
          <p className="text-2xl font-semibold text-slate-950">
            {comparison?.absolute_change_display ?? "—"}
          </p>
          <p className="mt-1 text-sm font-semibold text-cyan-700">
            {comparison?.percentage_change_display ?? "—"}
          </p>
        </div>
      </div>
      {comparison && (
        <p className="mt-5 border-t border-slate-100 pt-4 text-sm text-slate-500">
          {previousLabel}支出 <span className="font-semibold text-slate-800">{comparison.previous_spending_display}</span>
        </p>
      )}
    </section>
  );
}
