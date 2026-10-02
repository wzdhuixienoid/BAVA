import type { components } from "@banking/api-client";
import { StatusBadge } from "@/components/agent-ui/StatusBadge";

type Workflow = components["schemas"]["Workflow"];
export function WorkflowTimeline({ workflow }: { workflow: Workflow }) {
  const presentation = workflow.presentation;
  if (!presentation) return null;
  return <section aria-label="业务执行时间线" className="mt-4 rounded-xl border border-slate-200 bg-white p-3">
    <h3 className="text-xs font-semibold text-slate-700">业务执行进度</h3>
    <ol className="mt-3 grid gap-2 sm:grid-cols-2">
      {presentation.stages.map((stage, index) => <li key={stage.key} className="flex min-w-0 items-center justify-between gap-2 rounded-lg bg-slate-50 p-2">
        <span className="text-xs text-slate-700">{index + 1}. {stage.label}</span><StatusBadge status={stage.status} />
      </li>)}
    </ol>
    <div className="mt-3 flex flex-wrap gap-2 text-xs">
      {workflow.approval_summary && <span>用户确认：<StatusBadge status={workflow.approval_summary.status} /></span>}
      {workflow.reauth_summary && <span>强验证：<StatusBadge status={workflow.reauth_summary.status} /></span>}
      {workflow.operation_summary && <span>银行操作：<StatusBadge status={workflow.operation_summary.status} /></span>}
    </div>
    {!presentation.business_success && <p className="mt-3 text-xs text-slate-500">用户确认、身份验证或任务完成均不代表业务成功；最终结果以银行确认状态为准。</p>}
  </section>;
}
