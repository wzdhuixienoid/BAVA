import type { components } from "@banking/api-client";
import { dateTimeLabel } from "@/features/reports/presentation";
import { RiskDetails } from "@/features/workflows/RiskDetails";
import { WorkflowTimeline } from "@/features/workflows/WorkflowTimeline";
import { isConfirmedWorkflow } from "@/features/conversation/timeline";

type Workflow = components["schemas"]["Workflow"];

export function reviewField(workflow: Workflow, key: string): string {
  const review = workflow.state.review_payload as Record<string, unknown> | null | undefined;
  return typeof review?.[key] === "string" ? review[key] : "";
}

export function WorkflowReceipt({ workflow }: { workflow: Workflow }) {
  if (!isConfirmedWorkflow(workflow)) return null;
  const transfer = workflow.workflow_type === "TRANSFER";
  const operation = workflow.operation_summary;
  return (
    <section aria-label={transfer ? "转账回执" : "订阅取消回执"} className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-4">
      <p className="text-xs font-semibold text-emerald-700">✓ {transfer ? "转账已完成" : "订阅已取消"}</p>
      {transfer ? (
        <>
          <p className="mt-2 text-2xl font-semibold text-slate-950">{workflow.presentation?.amount_display ?? `${reviewField(workflow, "amount")} ${reviewField(workflow, "currency")}`}</p>
          <dl className="mt-3 grid grid-cols-[80px_minmax(0,1fr)] gap-y-2 text-sm">
            <dt className="text-slate-500">收款人</dt><dd className="break-words">{reviewField(workflow, "payee_display_name") || "—"} · {reviewField(workflow, "payee_masked_account")}</dd>
            <dt className="text-slate-500">转出账户</dt><dd className="break-words">{reviewField(workflow, "source_account_display_name") || "—"} · {reviewField(workflow, "source_account_masked_number")}</dd>
            <dt className="text-slate-500">收款银行</dt><dd>{reviewField(workflow, "payee_bank_name") || "—"}</dd>
          </dl>
        </>
      ) : (
        <p className="mt-3 font-medium">{reviewField(workflow, "merchant") || "订阅"}{reviewField(workflow, "plan_name") ? ` · ${reviewField(workflow, "plan_name")}` : ""}</p>
      )}
      {workflow.presentation?.transfer_state?.risk_decision && <RiskDetails risk={workflow.presentation.transfer_state.risk_decision} />}
      <WorkflowTimeline workflow={workflow} />
      {operation?.provider_reference && <p className="mt-3 break-all text-xs text-slate-500">参考号：{operation.provider_reference}</p>}
      <p className="mt-2 text-xs text-slate-400">{dateTimeLabel(operation?.completed_at ?? workflow.updated_at)}</p>
    </section>
  );
}
