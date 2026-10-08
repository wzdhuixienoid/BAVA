import type { components } from "@banking/api-client";
import { dateTimeLabel } from "./presentation";

type Review = components["schemas"]["SpendingReview"];

export function SpendingReview({ review }: { review?: Review | null }) {
  if (!review) return null;
  const items = review.items ?? [];
  return <section className={`rounded-2xl border px-6 py-5 ${items.length ? "border-amber-200 bg-amber-50/50" : "border-slate-200 bg-white"}`}>
    <h2 className="text-lg font-semibold text-slate-950">值得核对的交易</h2>
    <p className="mt-2 text-sm text-slate-700">{review.message}</p>
    {items.length > 0 && <ul className="mt-3 space-y-3">
      {items.map((item) => <li key={item.transaction_id} className="text-sm text-slate-700">
        <div className="flex flex-wrap justify-between gap-2"><span className="font-semibold">{item.merchant}</span><span>{item.amount_display} 元</span></div>
        <p className="mt-1 text-xs text-slate-500">{dateTimeLabel(item.occurred_at)} · {item.reason}</p>
      </li>)}
    </ul>}
    {items.length > 0 && <p className="mt-3 text-xs text-slate-500">这些提示不代表已确认欺诈。可回到对话询问该区间的异常交易明细。</p>}
    {(review.notes ?? []).map((note) => <p key={note} className="mt-2 text-xs text-slate-500">{note}</p>)}
  </section>;
}
