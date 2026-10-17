"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import type { components } from "@banking/api-client";
import { api } from "@/lib/api/client";
import { groupSchedules, ScheduleTaskCard } from "@/features/schedules/TaskCards";

export default function SchedulesPage() {
  const [rows,setRows] = useState<components["schemas"]["ScheduledTransfer"][]>([]);
  const [selected,setSelected] = useState<components["schemas"]["Workflow"] | null>(null);
  const [revoking,setRevoking] = useState<components["schemas"]["ScheduledTransfer"] | null>(null);
  const [deleting,setDeleting] = useState<components["schemas"]["ScheduledTransfer"] | null>(null);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  async function refresh() {try {setRows(await api.listSchedules()); if (selected) setSelected(await api.getWorkflow(selected.workflow_id));} catch(e) {setError(e instanceof Error ? e.message : "加载失败");}}
  useEffect(() => {
    let active = true;
    const load = () => api.listSchedules().then(value => {if(active)setRows(value);}).catch(e => {if(active)setError(String(e));});
    void load(); const timer = setInterval(() => void load(), 3000);
    return () => {active = false; clearInterval(timer);};
  },[]);
  const selectedWorkflowId = selected?.workflow_id;
  useEffect(() => {
    if (!selectedWorkflowId) return;
    let active = true;
    const timer = setInterval(() => void api.getWorkflow(selectedWorkflowId).then(value => {if(active)setSelected(value);}).catch(e=>{if(active)setError(String(e));}), 3000);
    return () => {active = false; clearInterval(timer);};
  },[selectedWorkflowId]);
  return <main className="min-h-screen bg-slate-50 p-8"><div className="mx-auto max-w-4xl"><div className="flex flex-wrap items-center justify-between gap-4"><h1 className="text-xl font-bold">预约与周期转账</h1><Link href="/transfers" className="shrink-0 text-sm text-cyan-700 underline">返回转账与收款</Link></div><p className="my-4 text-sm text-slate-600">仅支持站内 Mock。到时自动执行模拟转账，不冻结余额。创建预约与实际付款状态分别显示。</p>{error && <p className="text-red-700">{error}</p>}<div className="space-y-4">{groupSchedules(rows).map(group=><ScheduleTaskCard key={group.id} group={group} selected={selected} onRefresh={refresh} onRevoke={setRevoking} onDelete={setDeleting} onSelect={row=>void api.getWorkflow(row.workflow_id).then(setSelected).catch(e=>setError(String(e)))}/>)}</div>{deleting && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"><section role="dialog" aria-modal="true" aria-label="删除已取消预约" className="max-w-md rounded-xl bg-white p-5"><h2 className="font-semibold">删除已取消预约？</h2><p className="my-3 text-sm">从预约列表中移除这项任务。周期任务的所有已取消期次一并移除，审计与历史记录保留。</p><button disabled={busy} className="mr-4 rounded border px-3 py-2" onClick={()=>setDeleting(null)}>保留预约</button><button disabled={busy} className="rounded bg-red-700 px-3 py-2 text-white" onClick={()=>{setBusy(true);setError("");void api.scheduleAction(deleting.schedule_id,"delete",deleting.version).then(()=>{setDeleting(null);setSelected(null);return refresh();}).catch(e=>setError(String(e))).finally(()=>setBusy(false));}}>确认删除</button>{error && <p role="alert" className="mt-2 text-red-700">{error}</p>}</section></div>}{revoking && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"><section role="dialog" aria-modal="true" aria-label="撤销后续周期授权" className="max-w-md rounded-xl bg-white p-5"><h2 className="font-semibold">撤销后续周期授权？</h2><p className="my-3 text-sm">本周期尚未提交的期次将全部取消。已提交、结果未知或已成功的期次保留原操作状态，并继续查询；不会撤销已完成的付款。</p><button disabled={busy} className="mr-4 rounded border px-3 py-2" onClick={()=>setRevoking(null)}>保留周期</button><button disabled={busy} className="rounded bg-red-700 px-3 py-2 text-white" onClick={()=>{setBusy(true);setError("");void api.scheduleAction(revoking.schedule_id,"cancel-series",revoking.series_version!).then(()=>{setRevoking(null);return refresh();}).catch(e=>setError(String(e))).finally(()=>setBusy(false));}}>确认撤销</button>{error && <p role="alert" className="mt-2 text-red-700">{error}</p>}</section></div>}</div></main>;
}
