"use client";

import { useState } from "react";
import type { components } from "@banking/api-client";
import { api } from "@/lib/api/client";
import { dateTime } from "@/features/subscriptions/presentation";
import { StatusBadge } from "@/components/agent-ui/StatusBadge";
import { RiskBadge } from "@/features/workflows/RiskDetails";
import { WorkflowTimeline } from "@/features/workflows/WorkflowTimeline";

type Workflow = components["schemas"]["Workflow"];
type State = components["schemas"]["SubscriptionCancelWorkflowState"];

export function SubscriptionCancellationCard({ workflow, onRefresh }: { workflow: Workflow; onRefresh: () => Promise<void> }) {
  const state = (workflow.presentation?.subscription_state ?? workflow.state) as State;
  const review = state.review_payload;
  const operation = workflow.operation_summary;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function act(action: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await action(); await onRefresh(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "操作失败"); await onRefresh(); }
    finally { setBusy(false); }
  }

  return (
    <section className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3">
      <div className="flex items-start justify-between gap-3">
        <div><p className="text-[10px] font-semibold uppercase tracking-wider text-amber-800">订阅取消工作流</p><p className="mt-1 text-xs text-slate-500">版本 {workflow.version}</p></div>
        <StatusBadge status={operation?.status === "UNKNOWN" ? "UNKNOWN" : workflow.status} />
      </div>
      <div className="mt-3 rounded border border-amber-200 bg-white p-3 text-xs">
        <p className="font-bold text-amber-800">风险等级：{workflow.risk_level && <RiskBadge level={workflow.risk_level} />}</p>
        <p className="mt-2">{workflow.presentation?.approval_required ? "✓ 需要用户确认" : "确认要求待同步"}</p><p>{workflow.presentation?.reauthentication_required === false ? "○ 无需强验证" : "验证要求待同步"}</p>
      </div>
      <WorkflowTimeline workflow={workflow} />
      {workflow.status === "WAITING_FOR_INPUT" && state.required_input && (
        <div className="mt-3 space-y-2">
          <p className="text-sm font-semibold">{state.required_input.message}</p>
          {state.required_input.options.map((item, index) => (
            <div key={item.subscription_id ?? index} className="rounded border bg-white p-2">
              <p className="font-semibold">{item.merchant} · {item.plan_name ?? "套餐未提供"}</p>
              <p className="text-xs text-slate-500">{item.amount} {item.currency} · {item.management_type === "MANAGED" ? "可管理" : "仅检测"}</p>
              {item.cancellable && item.subscription_id && <button disabled={busy} className="mt-2 rounded bg-slate-900 px-3 py-1 text-xs font-semibold text-white" onClick={() => void act(() => api.selectSubscription(workflow.workflow_id, item.subscription_id!, workflow.version))}>选择</button>}
            </div>
          ))}
        </div>
      )}
      {review && (
        <dl className="mt-3 grid grid-cols-[82px_1fr] gap-y-2 rounded border border-amber-200 bg-white p-3 text-xs">
          <dt className="text-slate-500">商户</dt><dd className="font-semibold">{review.merchant}</dd>
          <dt className="text-slate-500">套餐</dt><dd>{review.plan_name ?? "—"}</dd>
          <dt className="text-slate-500">扣费</dt><dd>{workflow.presentation?.amount_display ?? `${review.amount} ${review.currency}`}</dd>
          <dt className="text-slate-500">下次扣费</dt><dd>{dateTime(review.next_billing_at)}</dd>
        </dl>
      )}
      {workflow.status === "READY_FOR_REVIEW" && review && (
        <button disabled={busy} className="mt-3 rounded bg-amber-700 px-3 py-2 text-xs font-semibold text-white" onClick={() => void act(() => api.approveWorkflow(workflow.workflow_id, workflow.version))}>确认取消</button>
      )}
      {workflow.status === "READY_FOR_COMMIT" && review && (
        <div className="mt-3"><p className="rounded bg-white p-2 text-xs font-semibold text-amber-800">可以提交不等于已取消。</p><button disabled={busy} className="mt-2 rounded bg-red-700 px-3 py-2 text-xs font-semibold text-white" onClick={() => void act(() => api.commitWorkflow(workflow.workflow_id, workflow.version))}>继续执行取消</button></div>
      )}
      {workflow.status === "COMMITTING" && <p className="mt-3 rounded bg-blue-50 p-2 text-xs text-blue-900">{operation?.status === "UNKNOWN" ? "结果确认中，请勿重复取消。" : "正在确认银行最终状态，请勿重复取消。"}</p>}
      {workflow.status === "SUCCEEDED" && operation?.status === "SUCCEEDED" && <p className="mt-3 rounded bg-emerald-100 p-3 text-sm font-semibold text-emerald-800">订阅已取消{operation.provider_reference ? `（${operation.provider_reference}）` : ""}</p>}
      {workflow.status === "FAILED" && <p className="mt-3 rounded bg-red-50 p-2 text-xs text-red-800">{state.error_message ?? state.error_code ?? "取消工作流失败"}</p>}
      {error && <p className="mt-2 text-xs text-red-700">{error}</p>}
    </section>
  );
}
