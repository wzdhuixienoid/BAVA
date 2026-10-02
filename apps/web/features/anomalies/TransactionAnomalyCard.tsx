import type { components } from "@banking/api-client";
import { dateTime } from "@/features/subscriptions/presentation";

export type TransactionAnomalySnapshot = components["schemas"]["TransactionAnomalySnapshot"];
const rules: Record<components["schemas"]["TransactionAnomalyType"], string> = {
  AMOUNT_SPIKE: "金额明显高于历史",
  RAPID_DUPLICATE: "短时间相同金额重复扣款",
  NEW_MERCHANT_HIGH_AMOUNT: "新商户高额消费",
  SUBSCRIPTION_PRICE_SPIKE: "订阅价格明显上涨",
};

export function TransactionAnomalyCard({ snapshot }: { snapshot: TransactionAnomalySnapshot }) {
  return (
    <section className="mt-3 min-w-0 rounded-xl border border-violet-200 bg-violet-50 p-4">
      <h2 className="font-semibold text-violet-900">异常交易分析</h2>
      <p className="mt-1 text-xs text-slate-500">分析区间：{dateTime(snapshot.analysis_period_started_at)} 至 {dateTime(snapshot.analysis_period_ended_at)}</p>
      <p className="mt-1 text-xs text-violet-800">异常提示 ≠ 已确认欺诈；请核对交易，不会自动触发安全锁定。</p>
      {snapshot.anomalies.length === 0 ? <p className="mt-3 text-sm text-slate-600">本次规则分析未发现明显异常。</p> : (
        <div className="mt-3 grid gap-3 xl:grid-cols-2">
          {snapshot.anomalies.map((item) => (
            <article key={item.transaction_id} className="min-w-0 rounded-lg border border-violet-200 bg-white p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div><p className="font-semibold">{item.merchant_display}</p><time dateTime={item.occurred_at} className="text-xs text-slate-500">{dateTime(item.occurred_at)}</time></div>
                <div className="text-right"><p className="font-bold">{item.amount_display}</p><p className={item.severity === "HIGH" ? "text-xs text-red-700" : "text-xs text-amber-700"}>{item.severity === "HIGH" ? "高度关注" : "中等关注"} · {item.currency}</p></div>
              </div>
              {item.anomaly_types.map((rule) => <div key={rule} className="mt-3 rounded bg-violet-50 p-2 text-xs">
                <p className="font-semibold text-violet-900">{rules[rule]}</p>
                <p className="mt-1 text-slate-500">规则：{rule}</p>
                <p className="mt-1">原因：{rules[rule]}，建议核对相关扣费。</p>
                <ul className="mt-1 space-y-1 text-slate-600">{(item.evidence_display?.[rule] ?? []).map((line, index) => <li key={index}>{line}</li>)}</ul>
              </div>)}
            </article>
          ))}
        </div>
      )}
      {snapshot.insufficient_baseline && <p className="mt-3 text-xs text-slate-500">部分金额规则因历史样本不足而未执行；重复扣款规则仍执行。</p>}
    </section>
  );
}
