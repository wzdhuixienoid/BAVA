import type { components } from "@banking/api-client";
import { StatusBadge } from "@/components/agent-ui/StatusBadge";
import { RiskDetails } from "@/features/workflows/RiskDetails";
import { ConditionCard } from "@/features/plans/ConditionCard";
import { dateTime } from "@/features/subscriptions/presentation";

type Trace = components["schemas"]["AuditTrace"];
const timeFactKeys = new Set(["evaluated_at", "locked_at", "invalidated_at", "scheduled_for", "execute_deadline", "expires_at", "approved_at", "verified_at", "consumed_at", "validated_at", "created_at", "completed_at", "submitted_at", "revoked_at", "authorized_at", "locked_until", "lease_expires_at", "next_reconcile_at"]);
function displayFact(key: string, value: string) { return timeFactKeys.has(key) ? dateTime(value) : value; }
const actorLabels = { USER: "用户", SYSTEM: "系统", AGENT: "注册 Agent", WORKFLOW: "工作流", SECURITY_GUARD: "安全控制", PROVIDER: "Mock Provider", RECOVERY_WORKER: "恢复执行" };

export function AuditUnavailable({ message }: { message: string }) {
  return <p role="alert" className="rounded border border-red-200 bg-red-50 p-3 text-xs text-red-800">审计链不可用：{message}</p>;
}

export function AuditTimeline({ trace }: { trace: Trace }) {
  const writes = trace.write_evidence;
  return <section aria-label="审计证据链" className="min-w-0 rounded-lg border border-slate-200 bg-white p-3 text-xs">
    <h3 className="font-semibold">Audit Evidence Chain</h3>
    <p className="mt-1 text-slate-500">{trace.history_note}</p>
    {trace.history_truncated && <p role="alert" className="mt-2 text-amber-800">证据超过展示上限，当前链不完整。</p>}
    <div className="mt-3 rounded bg-slate-50 p-3">
      <p className="font-semibold">{writes.business_success ? "业务成功：Workflow 与 Operation 均已确认" : "尚不能显示写业务成功"}</p>
      <p className="mt-1">Workflow {writes.workflow_count} · Approval {writes.approval_count} · Operation {writes.operation_count}</p>
      <p>Provider 提交意图 {writes.provider_submission_count} · Provider ledger {writes.provider_ledger_count}</p>
      {writes.no_write_started && <p className="mt-1">后端确认未启动写操作：无 Workflow、无 Operation、无 Provider ledger。</p>}
      {writes.skipped_write_step_ids.map((id) => <p key={id} className="mt-1 break-all">受条件约束的写步骤已跳过（SKIPPED）：{id}</p>)}
    </div>
    <ol className="mt-3 space-y-3 border-l-2 border-slate-200 pl-3">
      {trace.entries.map((entry) => <li key={entry.event_id} className="min-w-0 rounded border border-slate-100 p-3">
        <div className="flex flex-wrap items-center gap-2"><span className="text-slate-400">#{entry.sequence}</span><time dateTime={entry.timestamp}>{dateTime(entry.timestamp)}</time><span className="text-slate-500">{actorLabels[entry.actor_type]}</span>{entry.status && <StatusBadge status={entry.status} />}</div>
        <p className="mt-2 font-semibold">{entry.decision_summary}</p>
        {entry.risk_decision && <RiskDetails risk={entry.risk_decision} />}
        {entry.condition_decision && <ConditionCard decision={entry.condition_decision} sourceLabel={entry.condition_decision.source_step_id} />}
        <details className="mt-2"><summary className="cursor-pointer text-cyan-800">技术证据</summary>
          <p className="mt-2 break-all">{entry.event_type} · {entry.resource_type} · {entry.resource_id}</p>
          <dl className="mt-2 grid grid-cols-[100px_minmax(0,1fr)] gap-2">{(entry.facts ?? []).map((fact) => <div key={fact.key} className="contents"><dt className="text-slate-500">{fact.label}</dt><dd className="break-all">{displayFact(fact.key, fact.value)}</dd></div>)}</dl>
          <p className="mt-2 break-all">关联资源：{Object.entries(entry.related_resource_ids ?? {}).map(([key, value]) => `${key}=${value}`).join(" · ")}</p>
          {entry.condition_decision && <p className="mt-2 break-all">Source hash：{entry.condition_decision.source_output_hash}</p>}
        </details>
      </li>)}
    </ol>
    <details className="mt-3"><summary className="cursor-pointer font-semibold">当前授权与执行资源（当前快照）</summary>
      {trace.resources.map((resource) => <article key={`${resource.resource_type}-${resource.resource_id}`} className="mt-2 rounded bg-slate-50 p-3">
        <p className="break-all">{resource.resource_type} · {resource.resource_id}</p><StatusBadge status={resource.status} />
        <dl className="mt-2 grid grid-cols-[100px_minmax(0,1fr)] gap-2">{resource.facts.map((fact) => <div key={fact.key} className="contents"><dt>{fact.label}</dt><dd className="break-all">{displayFact(fact.key, fact.value)}</dd></div>)}</dl>
      </article>)}
    </details>
    <p className="mt-3 break-all text-slate-400">Trace / Task：{trace.trace_id} · 查询时间 {dateTime(trace.generated_at)}</p>
  </section>;
}
