"use client";

import { useState } from "react";
import type { components } from "@banking/api-client";
import { api } from "@/lib/api/client";
import { TransferWorkflowCard } from "@/features/workflows/transfer/TransferWorkflowCard";
import { SubscriptionCancellationCard } from "@/features/workflows/subscriptions/SubscriptionCancellationCard";
import { SubscriptionSummaryCard } from "@/features/subscriptions/SubscriptionSummaryCard";

type Plan = components["schemas"]["Plan"];
type Workflow = components["schemas"]["Workflow"];
type SubscriptionSnapshot = components["schemas"]["SubscriptionAnalysisSnapshot"];

const predicates: Record<string, string> = {
  ACCOUNT_BALANCE_AT_LEAST: "账户余额",
  MONTHLY_SPENDING_AT_LEAST: "本月支出",
  SUBSCRIPTION_MONTHLY_COST_AT_LEAST: "每月订阅成本",
};
const labels: Record<string, string> = {
  RUNNING: "执行中", PENDING: "等待前置步骤", WAITING_USER: "等待你的操作",
  WAITING_EXTERNAL: "等待外部结果", PAUSED: "已转为手动处理", COMPLETED: "已完成",
  FAILED: "执行失败", CANCELLED: "已取消", SKIPPED: "前置步骤未完成，已跳过",
};

export function PlanCard({ plan, workflows, onRefresh }: {
  plan: Plan; workflows: Workflow[]; onRefresh: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function act(action: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await action(); await onRefresh(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "计划操作失败"); }
    finally { setBusy(false); }
  }
  const positions = new Map(plan.steps.map((step, index) => [step.step_id, index + 1]));
  const canTakeOver = ["RUNNING", "WAITING_USER", "WAITING_EXTERNAL"].includes(plan.status);
  return (
    <section className="rounded-lg border border-indigo-200 bg-white p-3 text-sm">
      <div className="flex items-start justify-between gap-3">
        <p className="font-semibold text-indigo-950">{plan.goal_summary}</p>
        <span className="shrink-0 rounded bg-indigo-50 px-2 py-1 text-xs">{labels[plan.status]}</span>
      </div>
      {plan.manual_takeover && <p className="mt-3 rounded bg-amber-50 p-2 text-xs">自动任务编排已暂停。你可以继续手动处理当前业务步骤。</p>}
      <ol className="mt-3 space-y-3">
        {plan.steps.map((step, index) => {
          const workflow = workflows.find((item) => item.workflow_id === step.linked_workflow_id);
          const decision = step.condition_decision;
          const spec = step.condition_spec;
          const snapshot = step.result_summary?.subscription_analysis_snapshot as SubscriptionSnapshot | undefined;
          return (
            <li key={step.step_id} className="rounded border border-slate-200 p-2">
              <div className="flex items-start justify-between gap-2">
                <p className="font-medium">{index + 1}. {step.display_title}</p>
                <span className="text-xs text-slate-600">{step.status === "COMPLETED" ? "✓ " : ""}{decision ? (decision.outcome === "TRUE" ? "条件满足" : "条件未满足") : step.error_code === "CONDITION_NOT_MET" ? "条件未满足，已跳过" : labels[step.status]}</span>
              </div>
              {step.depends_on.length > 0 && <p className="mt-1 text-xs text-slate-500">依赖：{step.depends_on.map((id) => `步骤 ${positions.get(id)}`).join("、")}</p>}
              {spec && <p className="mt-2 text-xs text-slate-700">条件：{predicates[spec.predicate]}不少于 {spec.threshold} {spec.currency ?? "源结果币种"}</p>}
              {decision && <p className="mt-1 text-xs text-slate-700">实际值：{decision.actual_value} {decision.currency} · 阈值：{decision.threshold_value} {decision.currency}</p>}
              {step.guard_condition_step_id && <p className="mt-1 text-xs text-slate-500">仅在步骤 {positions.get(step.guard_condition_step_id)} 条件满足时执行</p>}
              {step.error_code === "CONDITION_NOT_MET" && <p className="mt-2 text-xs text-slate-600">条件未满足，后续步骤已跳过</p>}
              {step.error_code && step.error_code !== "CONDITION_NOT_MET" && <p className="mt-2 text-xs text-red-700">{step.error_code}</p>}
              {snapshot && <SubscriptionSummaryCard snapshot={snapshot} />}
              {workflow?.workflow_type === "TRANSFER" && <TransferWorkflowCard workflow={workflow} onRefresh={onRefresh} />}
              {workflow?.workflow_type === "SUBSCRIPTION_CANCEL" && <SubscriptionCancellationCard workflow={workflow} onRefresh={onRefresh} />}
              {step.rollback_allowed && step.status !== "PENDING" && <button disabled={busy} className="mt-2 text-xs font-medium text-indigo-700 disabled:opacity-40" onClick={() => void act(() => api.rollbackPlan(plan.plan_id, step.step_id))}>回退并重新执行</button>}
            </li>
          );
        })}
      </ol>
      <div className="mt-3 flex gap-2">
        {canTakeOver && <button disabled={busy} className="rounded border px-3 py-1 text-xs disabled:opacity-40" onClick={() => void act(() => api.takeOverPlan(plan.plan_id))}>转为手动处理</button>}
        {plan.status === "PAUSED" && <button disabled={busy} className="rounded bg-indigo-700 px-3 py-1 text-xs text-white disabled:opacity-40" onClick={() => void act(() => api.resumePlan(plan.plan_id))}>继续自动执行</button>}
      </div>
      {error && <p role="alert" className="mt-2 text-xs text-red-700">{error}</p>}
    </section>
  );
}
