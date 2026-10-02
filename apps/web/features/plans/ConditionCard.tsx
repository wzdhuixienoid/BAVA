import type { components } from "@banking/api-client";
import { predicateLabels } from "@/lib/presentation/status";
import { dateTime } from "@/features/subscriptions/presentation";

type Decision = components["schemas"]["ConditionDecision"];
export function ConditionCard({ decision, sourceLabel }: { decision: Decision; sourceLabel: string }) {
  return <section aria-label="条件判断" className={`mt-2 rounded-lg border p-3 text-xs ${decision.outcome === "TRUE" ? "border-emerald-200 bg-emerald-50" : "border-slate-200 bg-slate-50"}`}>
    <div className="flex flex-wrap justify-between gap-2"><p className="font-semibold">{predicateLabels[decision.predicate]} {decision.threshold_display}</p><strong>{decision.outcome}</strong></div>
    <dl className="mt-2 grid grid-cols-[76px_minmax(0,1fr)] gap-2">
      <dt>实际值</dt><dd className="font-semibold">{decision.actual_display}</dd><dt>阈值</dt><dd>{decision.threshold_display}</dd>
      <dt>币种</dt><dd>{decision.currency}</dd><dt>来源步骤</dt><dd>{sourceLabel}</dd><dt>判断时间</dt><dd><time dateTime={decision.evaluated_at}>{dateTime(decision.evaluated_at)}</time></dd>
    </dl>
    <p className="mt-2 text-slate-600">{decision.outcome === "TRUE" ? "条件满足不等于转账授权；后续仍需 Workflow 风险评估、确认、验证及银行执行。" : "条件未满足；受此条件约束的写步骤由后端跳过。"}</p>
  </section>;
}
