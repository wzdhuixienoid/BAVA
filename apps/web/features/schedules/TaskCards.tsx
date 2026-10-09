import type { components } from "@banking/api-client";
import { queryTime } from "@/lib/presentation/time";
import { TransferWorkflowCard } from "@/features/workflows/transfer/TransferWorkflowCard";

export type Schedule = components["schemas"]["ScheduledTransfer"];
export type ScheduleGroup = { id: string; rows: Schedule[]; primary: Schedule };
const labels: Record<string, string> = {PENDING_AUTHORIZATION:"待授权", SCHEDULED:"已预约", EXECUTING:"执行中", UNKNOWN:"结果未知", SUCCEEDED:"付款成功", FAILED:"失败", CANCELLED:"已取消", EXPIRED:"已过期"};

export function groupSchedules(rows: Schedule[]): ScheduleGroup[] {
  const grouped = new Map<string, Schedule[]>();
  for (const row of rows) {
    const id = row.series_id ?? row.schedule_id;
    grouped.set(id, [...(grouped.get(id) ?? []), row]);
  }
  return Array.from(grouped).map(([id, items]) => {
    items.sort((a, b) => (a.occurrence_index ?? 0) - (b.occurrence_index ?? 0));
    return {id, rows: items, primary: items[0]};
  }).sort((a, b) => (b.primary.created_at ?? "").localeCompare(a.primary.created_at ?? ""));
}

function groupStatus(group: ScheduleGroup): string {
  if (!group.primary.series_id) return labels[group.primary.status] ?? group.primary.status;
  const statuses = group.rows.map(row => row.status);
  if (statuses.includes("UNKNOWN")) return "结果确认中";
  if (statuses.includes("EXECUTING")) return "执行中";
  if (group.rows.length === group.primary.recurrence?.count && statuses.every(status => status === "SUCCEEDED")) return "全部付款成功";
  if (statuses.every(status => status === "CANCELLED")) return "已取消";
  if (statuses.some(status => status === "SUCCEEDED")) return "部分付款成功";
  if (statuses.some(status => status === "SCHEDULED")) return "已预约";
  return "已结束，查看逐期结果";
}

export function ScheduleTaskCard({ group, selected, onSelect, onRevoke, onDelete, onRefresh }: {
  group: ScheduleGroup;
  selected: components["schemas"]["Workflow"] | null;
  onSelect: (row: Schedule) => void;
  onRevoke: (row: Schedule) => void;
  onDelete?: (row: Schedule) => void;
  onRefresh: () => Promise<void>;
}) {
  const row = group.primary;
  const periodic = Boolean(row.series_id);
  const times = group.rows.map(item => item.scheduled_for).filter((value): value is string => Boolean(value));
  const successful = group.rows.filter(item => item.status === "SUCCEEDED").length;
  const cancelled = group.rows.filter(item => item.status === "CANCELLED").length;
  const pending = group.rows.filter(item => item.status === "SCHEDULED").length;
  const status = groupStatus(group);
  const active = group.rows.some(item => ["SCHEDULED", "EXECUTING"].includes(item.status) && !item.operation_id);
  const ownedSelection = selected && group.rows.some(item => item.workflow_id === selected.workflow_id) ? selected : null;
  return <article aria-label={row.task_title} className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
    <div className="p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h2 className="min-w-0 flex-1 break-words text-base font-semibold leading-7 text-slate-900">{row.task_title}{row.remark && <span className="font-normal text-slate-600"> · {row.remark}</span>}</h2>
        <span className={`rounded-full px-3 py-1 text-xs font-medium ${group.rows.some(item => ["UNKNOWN","FAILED"].includes(item.status)) ? "bg-amber-50 text-amber-800" : status.includes("成功") ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>{status}</span>
      </div>
      <p className="mt-2 text-sm leading-6 text-slate-600">执行时间：{times.length ? `${queryTime(times[0])}${periodic && times.length > 1 ? ` 至 ${queryTime(times[times.length - 1])}` : ""}` : "待补充时间"}</p>
      {periodic ? <>
        <p className="mt-3 text-sm text-slate-500">每月 {row.recurrence?.day} 日 · 共 {row.recurrence?.count ?? group.rows.length} 期{row.series_revoked ? " · 后续授权已撤销" : ""}</p>
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-600"><span>付款成功 {successful} 期</span><span>待执行 {pending} 期</span>{cancelled > 0 && <span>已取消 {cancelled} 期</span>}</div>
        <details className="mt-4 border-t border-slate-100 pt-4">
          <summary className="cursor-pointer text-sm font-medium text-cyan-700">查看 {group.rows.length} 期计划与状态</summary>
          <ol className="mt-3 divide-y divide-slate-100">{group.rows.map(item => <li key={item.schedule_id} className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3 text-sm"><span className="text-slate-400">第 {item.occurrence_index} 期</span><time className="flex-1 text-slate-700" dateTime={item.scheduled_for ?? undefined}>{item.scheduled_for ? queryTime(item.scheduled_for) : "待补充时间"}</time><span className="text-slate-600">{labels[item.status] ?? item.status}</span><button className="text-cyan-700 hover:underline" onClick={()=>onSelect(item)}>{item.status === "UNKNOWN" ? "查询原操作" : "详情"}</button></li>)}</ol>
        </details>
        {!row.series_revoked && active && <button className="mt-4 text-sm text-red-700 hover:underline" onClick={()=>onRevoke(row)}>撤销后续周期授权</button>}
      </> : <button className="mt-4 text-sm font-medium text-cyan-700 hover:underline" onClick={()=>onSelect(row)}>详情与编辑</button>}
      {onDelete && group.rows.every(item=>item.status === "CANCELLED" && !item.operation_id) && <button className="ml-4 mt-4 text-sm text-red-700 hover:underline" onClick={()=>onDelete(row)}>删除预约</button>}
      {ownedSelection && <div className="mt-4 border-t border-slate-100 pt-2"><TransferWorkflowCard workflow={ownedSelection} onRefresh={onRefresh}/></div>}
    </div>
  </article>;
}
