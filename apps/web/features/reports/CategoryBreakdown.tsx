import type { components } from "@banking/api-client";
import { categoryLabel } from "./presentation";

type Category = components["schemas"]["ReportCategory"];

export function CategoryBreakdown({ categories }: { categories: Category[] }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold text-slate-950">分类构成</h2>
      <div className="mt-4 divide-y divide-slate-100">
        {categories.map((item) => (
          <div key={item.category} className="grid grid-cols-[1fr_auto] gap-4 py-3 first:pt-0 last:pb-0">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-slate-900">{categoryLabel(item.category)}</span>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                  {item.share_display}
                </span>
              </div>
              <p className="mt-1 text-xs text-slate-400">{item.transaction_count} 笔</p>
            </div>
            <div className="text-right">
              <p className="font-semibold text-slate-950">{item.amount_display}</p>
              {item.absolute_change_display && (
                <p className="mt-1 text-xs text-slate-500">
                  较上月 {item.absolute_change_display} · {item.percentage_change_display ?? "—"}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
