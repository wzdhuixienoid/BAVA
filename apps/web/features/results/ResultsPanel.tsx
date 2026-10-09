"use client";

import { useState } from "react";
import type { components } from "@banking/api-client";
import { dateTimeLabel, periodLabel } from "@/features/reports/presentation";
import { isConfirmedWorkflow } from "@/features/conversation/timeline";
import type { AARequest } from "@/features/aa/types";
import { reviewField } from "./WorkflowReceipt";

type Report = components["schemas"]["ReportListItem"];
type Workflow = components["schemas"]["Workflow"];

type CompletedEvent = { id: string; time: string; type: string; title: string; summary: string; search: string };

export function ResultsPanel({ reports, workflows, aaRequests = [], onLocateResult }: {
  reports: Report[]; workflows: Workflow[]; aaRequests?: AARequest[]; onLocateResult: (resultId: string) => void;
}) {
  const [query, setQuery] = useState("");
  const events: CompletedEvent[] = [
    ...aaRequests.filter(row => row.status === "COLLECTED" || row.status === "PARTIAL_CLOSED").map(row => ({id:`aa-${row.request_id}`, time:row.created_at, type:"AA 收款结果", title:row.snapshot?.remark || "AA 收款", summary:`已收 ¥${row.received} · 未收 ¥${row.outstanding}`, search:`${row.snapshot?.total} ${row.snapshot?.remark} ${row.received}`})),
    ...reports.map((report) => ({
      id: `report-${report.report_id}`, time: report.created_at, type: "消费报告",
      title: `${periodLabel(report.period)}消费报告`, summary: report.total_spending_display,
      search: `${report.period} ${report.headline} ${report.total_spending_display}`,
    })),
    ...workflows.filter(isConfirmedWorkflow).map((workflow) => {
      const resume = workflow.workflow_type === "SUBSCRIPTION_RESUME";
      const transfer = workflow.workflow_type === "TRANSFER";
      const name = reviewField(workflow, transfer ? "payee_display_name" : "merchant");
      const amount = workflow.presentation?.amount_display ?? `${reviewField(workflow, "amount")} ${reviewField(workflow, "currency")}`;
      return {
        id: `workflow-${workflow.workflow_id}`,
        time: workflow.operation_summary?.completed_at ?? workflow.updated_at,
        type: transfer ? "转账" : (resume ? "订阅恢复" : "订阅取消"),
        title: transfer ? `转账给${name || "收款人"}` : `${name || "订阅"}${resume ? "已恢复续费" : "已取消"}`,
        summary: transfer ? amount : reviewField(workflow, "plan_name"),
        search: `${name} ${amount} ${workflow.operation_summary?.provider_reference ?? ""}`,
      };
    }),
  ].sort((a, b) => b.time.localeCompare(a.time));
  const term = query.trim().toLocaleLowerCase();
  const visible = events.filter((event) => `${event.type} ${event.title} ${event.summary} ${event.search} ${event.time}`.toLocaleLowerCase().includes(term));

  return (
    <aside aria-label="已完成事件" className="flex h-full min-h-0 min-w-0 flex-col border-slate-200 bg-slate-50 lg:border-l">
      <div className="shrink-0 border-b border-slate-200 p-4">
        <h2 className="text-sm font-semibold text-slate-900">已完成事件 <span className="ml-1 text-xs font-normal text-slate-400">{events.length}</span></h2>
        <p className="mt-1 text-xs text-slate-500">本对话的事件索引，点击查看对话中的结果</p>
        <input aria-label="搜索已完成事件" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索报告、收款人、金额…"
          className="mt-3 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500" />
      </div>
      <div aria-label="完成事件索引" className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 py-2">
        {events.length === 0 && <p className="px-2 py-6 text-center text-xs leading-relaxed text-slate-400">已完成的报告、转账和订阅管理会收录在这里。</p>}
        {events.length > 0 && visible.length === 0 && <p className="px-2 py-6 text-center text-xs text-slate-400">没有匹配的已完成事件。</p>}
        {visible.map((event) => <button key={event.id} onClick={() => onLocateResult(event.id)} aria-label={`在对话中查看：${event.title}`}
          className="group block w-full border-b border-slate-200 px-2 py-4 text-left hover:rounded-lg hover:bg-white focus-visible:rounded-lg focus-visible:outline-cyan-500">
          <span className="mb-1 flex items-center justify-between text-[10px] text-slate-400"><span>{event.type}</span><span className="text-emerald-600">已完成</span></span>
          <span className="block truncate text-xs font-semibold text-slate-800">{event.title}</span>
          {event.summary && <span className="mt-1 block truncate text-xs text-slate-500">{event.summary}</span>}
          <span className="mt-2 flex items-center justify-between text-[10px] text-slate-400"><time dateTime={event.time}>{dateTimeLabel(event.time)}</time><span className="text-cyan-700 group-hover:underline">定位到对话 ↗</span></span>
        </button>)}
      </div>
    </aside>
  );
}
