"use client";

import { ConditionCard } from "./ConditionCard";
import { StatusBadge } from "@/components/agent-ui/StatusBadge";
import { capabilityLabels, predicateLabels } from "@/lib/presentation/status";
import { useState } from "react";
import type { components } from "@banking/api-client";
import { api } from "@/lib/api/client";
import { TransferWorkflowCard } from "@/features/workflows/transfer/TransferWorkflowCard";
import { SubscriptionCancellationCard } from "@/features/workflows/subscriptions/SubscriptionCancellationCard";
import { SubscriptionSummaryCard } from "@/features/subscriptions/SubscriptionSummaryCard";

type Plan = components["schemas"]["Plan"];
type Workflow = components["schemas"]["Workflow"];
type SubscriptionSnapshot = components["schemas"]["SubscriptionAnalysisSnapshot"];

export function PlanCard({ plan, workflows, onRefresh, processOnly = false }: {
  plan: Plan; workflows: Workflow[]; onRefresh: () => Promise<void>; processOnly?: boolean;
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
    <section className={processOnly ? "border-l-2 border-slate-200 pl-4 text-xs" : "rounded-lg border border-indigo-200 bg-white p-3 text-sm"}>
      <div className="flex items-start justify-between gap-3">
        <p className="font-semibold text-indigo-950">{plan.goal_summary}</p>
        <StatusBadge status={plan.status} />
      </div>
      {plan.manual_takeover && <p className="mt-3 rounded bg-amber-50 p-2 text-xs">自动任务编排已暂停。你可以继续手动处理当前业务步骤。</p>}
      <p className="mt-2 text-xs text-slate-500">Plan DAG · 箭头与依赖来自后端计划；条件 TRUE 分支进入流程，FALSE 分支跳过受保护步骤。</p>
      <ol aria-label="计划依赖图" className="mt-3 space-y-3">
        {plan.steps.map((step, index) => {
          const workflow = workflows.find((item) => item.workflow_id === step.linked_workflow_id);
          const decision = step.condition_decision;
          const spec = step.condition_spec;
          const snapshot = step.result_summary?.subscription_analysis_snapshot as SubscriptionSnapshot | undefined;
          return (
            <li key={step.step_id} className={processOnly ? "py-1" : "rounded border border-slate-200 p-2"}>
              <div className="flex items-start justify-between gap-2">
                <p className="font-medium">{index + 1}. {step.display_title}</p>
                <StatusBadge status={step.status} />
              </div>
              <p className="mt-1 text-xs text-indigo-700">{step.step_kind === "CONDITION" ? "条件节点" : "能力节点"} · {step.capability ? capabilityLabels[step.capability] : "确定性条件判断"}</p>
              {step.depends_on.length > 0 && <p className="mt-1 text-xs text-slate-500">↓ 前置依赖：{step.depends_on.map((id) => `步骤 ${positions.get(id)}`).join("、")}</p>}
              {spec && <p className="mt-2 text-xs text-slate-700">条件：{predicateLabels[spec.predicate]} {spec.threshold} {spec.currency ?? "源结果币种"}</p>}
              {decision && <ConditionCard decision={decision} sourceLabel={`步骤 ${positions.get(decision.source_step_id) ?? "待同步"}`} />}
              {step.guard_condition_step_id && <p className="mt-1 text-xs text-slate-500">Guard：步骤 {positions.get(step.guard_condition_step_id)} → TRUE 才能执行</p>}
              {step.error_code === "CONDITION_NOT_MET" && <p className="mt-2 text-xs text-slate-600">FALSE → 此写步骤已跳过，未执行转账或取消</p>}
              {step.error_code && step.error_code !== "CONDITION_NOT_MET" && <p className="mt-2 text-xs text-red-700">{step.error_code}</p>}
              {!processOnly && snapshot && <SubscriptionSummaryCard snapshot={snapshot} />}
              {!processOnly && workflow?.workflow_type === "TRANSFER" && <TransferWorkflowCard workflow={workflow} onRefresh={onRefresh} />}
              {!processOnly && workflow?.workflow_type === "SUBSCRIPTION_CANCEL" && <SubscriptionCancellationCard workflow={workflow} onRefresh={onRefresh} />}
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
