import type { components } from "@banking/api-client";
import { categoryLabel } from "./presentation";

type Category = components["schemas"]["ReportCategory"];

export function CategoryBreakdown({ categories, yearly = false, columns = false }: { categories: Category[]; yearly?: boolean; columns?: boolean }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold text-slate-950">分类构成</h2>
      <div className={columns ? "mt-4 grid gap-x-8 sm:grid-cols-2" : "mt-4 divide-y divide-slate-100"}>
        {categories.map((item) => (
          <div key={item.category} className={`grid min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-4 py-3 ${columns ? "border-b border-slate-100" : "first:pt-0 last:pb-0"}`}>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-slate-900">{categoryLabel(item.category)}</span>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                  {item.share_display}
                </span>
              </div>
              <p className="mt-1 text-xs text-slate-400">{item.transaction_count} 笔</p>
              <div aria-label={`${categoryLabel(item.category)}占比 ${item.share_display}`} className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
                <div className="h-full rounded-full bg-cyan-500" style={{ width: item.share_display }} />
              </div>
            </div>
            <div className="text-right">
              <p className="font-semibold text-slate-950">{item.amount_display}</p>
              {item.absolute_change_display && (
                <p className="mt-1 text-xs text-slate-500">
                  {yearly ? "较上年" : "较上月"} {item.absolute_change_display} · {item.percentage_change_display ?? "—"}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
