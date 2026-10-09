import type { components } from "@banking/api-client";
import { dateTime } from "./presentation";
import { StatusBadge } from "@/components/agent-ui/StatusBadge";
import Link from "next/link";
import { CancelSubscriptionButton } from "./CancelSubscriptionButton";

type Snapshot = components["schemas"]["SubscriptionAnalysisSnapshot"];
type Subscription = components["schemas"]["SubscriptionItem"];

function SubscriptionRow({ item, generatedAt, onCancelled }: { item: Subscription; generatedAt: string; onCancelled?: (item: Subscription) => void }) {
  const expiredEstimate = item.next_billing_is_estimated && item.next_billing_at && new Date(item.next_billing_at) < new Date(generatedAt);
  return (
    <article className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-semibold text-slate-900">{item.merchant}</p>
          <p className="mt-1 text-xs text-slate-500">{item.plan_name ?? "套餐未提供"}</p>
        </div>
        <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${
          item.management_type === "MANAGED"
            ? "bg-emerald-100 text-emerald-800"
            : "bg-slate-100 text-slate-700"
        }`}>
          {item.management_type === "MANAGED" ? "可管理" : "到商户管理"}
        </span>
      </div>
      <dl className="mt-3 grid grid-cols-[92px_1fr] gap-y-1 text-xs">
        <dt className="text-slate-500">状态</dt><dd><StatusBadge status={item.status} /></dd>
        <dt className="text-slate-500">月度成本</dt><dd className="font-semibold">{item.monthly_cost_display ?? "未提供"}</dd>
        <dt className="text-slate-500">预计年度成本</dt><dd>{item.annual_projected_cost_display ?? "未提供"}</dd>
        <dt className="text-slate-500">周期</dt><dd>{item.billing_interval === "MONTHLY" ? "每月" : "每年"}</dd>
        <dt className="text-slate-500">最近扣费</dt><dd>{item.last_charge_date ?? "暂无扣费记录"}</dd>
        <dt className="text-slate-500">当前金额</dt><dd className="font-semibold">{item.contract_amount_display ?? item.last_charge_display ?? `¥${item.last_charge_amount}`}</dd>
        <dt className="text-slate-500">{item.next_billing_is_estimated ? "预计下次扣款" : "下次扣款"}</dt>
        <dd>{item.status === "CANCELLED" ? "已取消" : expiredEstimate ? "待确认" : dateTime(item.next_billing_at)}</dd>
      </dl>
      {item.price_change_amount != null && (
        <p className="mt-2 rounded bg-amber-50 p-2 text-xs font-semibold text-amber-800">
          最近一期变动 {item.price_change_display ?? `¥${item.price_change_amount}`}
          {item.price_change_percent != null ? `（${item.price_change_percent_display ?? `${item.price_change_percent}%`}）` : ""}
        </p>
      )}
      {item.cancellable && item.subscription_id && (onCancelled ? <CancelSubscriptionButton item={item} onCancelled={onCancelled} /> : <Link className="mt-3 inline-block rounded border border-amber-300 px-3 py-2 text-xs font-semibold text-amber-900" href={`/?cancel=${encodeURIComponent(item.merchant)}`}>取消订阅</Link>)}
      {item.resumable && item.subscription_id && <Link className="mt-3 inline-block rounded border border-red-300 px-3 py-2 text-xs font-semibold text-red-800" href={`/?resume=${encodeURIComponent(item.merchant)}`}>重新订阅</Link>}
      {item.management_type === "DETECTED_ONLY" && (
        <p className="mt-2 text-xs leading-5 text-slate-600">
          请前往对应商户确认续费安排或取消订阅。
        </p>
      )}
    </article>
  );
}

export function SubscriptionSummaryCard({ snapshot, compact = false, onCancelled }: { snapshot: Snapshot; compact?: boolean; onCancelled?: (item: Subscription) => void }) {
  return (
    <section className="mt-3 rounded-xl border border-cyan-200 bg-cyan-50 p-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-cyan-800">订阅分析</p>
          <p className="mt-1 text-sm font-semibold text-slate-900">
            {snapshot.subscriptions.length} 项周期扣费
          </p>
        </div>
        <div className="text-right text-xs text-slate-600">
          {snapshot.monthly_cost_by_currency.map((item) => (
            <p key={item.currency}>每月费用 {item.amount_display ?? `¥${item.amount}`}</p>
          ))}
        </div>
      </div>
      {!compact && (
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          {snapshot.subscriptions.map((item, index) => (
            <SubscriptionRow key={item.subscription_id ?? `${item.merchant}-${item.currency}-${index}`} item={item} generatedAt={snapshot.generated_at} onCancelled={onCancelled} />
          ))}
        </div>
      )}
      {compact && snapshot.price_changes.length > 0 && (
        <p className="mt-2 text-xs text-amber-800">涨价 / 价格变动：{snapshot.price_changes.map((item) => item.merchant).join("、")}</p>
      )}
    </section>
  );
}
