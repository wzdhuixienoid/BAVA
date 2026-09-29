type Evidence = {
  baseline_median?: string | null;
  ratio?: string | null;
  duplicate_count?: number | null;
  window_minutes?: number | null;
  previous_amount?: string | null;
  increase_percent?: string | null;
};
type Item = {
  transaction_id: string;
  occurred_at: string;
  merchant_display: string;
  amount: string;
  currency: string;
  anomaly_types: string[];
  severity: "MEDIUM" | "HIGH";
  evidence: Partial<Record<string, Evidence>>;
};
export type TransactionAnomalySnapshot = {
  anomalies: Item[];
  insufficient_baseline: boolean;
};

const anomalyLabels: Record<string, string> = {
  AMOUNT_SPIKE: "金额明显高于历史",
  RAPID_DUPLICATE: "短时间相同金额重复扣款",
  NEW_MERCHANT_HIGH_AMOUNT: "新商户高额消费",
  SUBSCRIPTION_PRICE_SPIKE: "订阅价格明显上涨",
};

function money(value: string, currency: string) {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(Number(value));
}

function reason(item: Item) {
  const amount = item.evidence.AMOUNT_SPIKE;
  if (amount?.baseline_median && amount.ratio) {
    return `本笔 ${money(item.amount, item.currency)}，历史中位数 ${money(amount.baseline_median, item.currency)}，约为平时 ${amount.ratio} 倍。`;
  }
  const duplicate = item.evidence.RAPID_DUPLICATE;
  if (duplicate?.duplicate_count && duplicate.window_minutes) {
    return `${duplicate.window_minutes} 分钟内发现 ${duplicate.duplicate_count} 笔相同金额扣款。`;
  }
  const merchant = item.evidence.NEW_MERCHANT_HIGH_AMOUNT;
  if (merchant?.baseline_median && merchant.ratio) {
    return `近 90 天未发现该商户，金额约为历史中位数的 ${merchant.ratio} 倍。`;
  }
  const subscription = item.evidence.SUBSCRIPTION_PRICE_SPIKE;
  if (subscription?.previous_amount && subscription.increase_percent) {
    return `上期 ${money(subscription.previous_amount, item.currency)}，本期 ${money(item.amount, item.currency)}，上涨 ${subscription.increase_percent}%。`;
  }
  return "这笔交易与历史模式不同，建议关注。";
}

export function TransactionAnomalyCard({ snapshot }: { snapshot: TransactionAnomalySnapshot }) {
  return (
    <section className="mt-3 rounded-lg border border-violet-200 bg-violet-50 p-3">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-violet-700">
        异常交易分析
      </p>
      {snapshot.anomalies.length === 0 ? (
        <p className="mt-2 text-xs text-slate-700">
          在本次分析使用的确定性规则下，没有发现明显异常。这不代表账户绝对安全。
        </p>
      ) : (
        <div className="mt-3 space-y-2">
          {snapshot.anomalies.map((item) => (
            <article key={item.transaction_id} className="rounded border border-violet-200 bg-white p-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold text-slate-900">{item.merchant_display}</p>
                  <p className="mt-1 text-xs text-slate-500">
                    {new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium" }).format(
                      new Date(item.occurred_at),
                    )}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-sm font-bold">{money(item.amount, item.currency)}</p>
                  <span className={item.severity === "HIGH" ? "text-xs font-semibold text-red-700" : "text-xs font-semibold text-amber-700"}>
                    {item.severity === "HIGH" ? "高度关注" : "中等关注"}
                  </span>
                </div>
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {item.anomaly_types.map((type) => (
                  <span key={type} className="rounded bg-violet-100 px-2 py-1 text-[10px] font-semibold text-violet-800">
                    {anomalyLabels[type] ?? type}
                  </span>
                ))}
              </div>
              <p className="mt-2 text-xs leading-5 text-slate-700">{reason(item)}</p>
            </article>
          ))}
        </div>
      )}
      {snapshot.insufficient_baseline && (
        <p className="mt-2 text-[10px] text-slate-500">
          部分金额规则因历史样本不足而未执行；短时间重复扣款规则仍正常执行。
        </p>
      )}
    </section>
  );
}
