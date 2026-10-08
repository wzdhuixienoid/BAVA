"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { components } from "@banking/api-client";
import { ReportList } from "@/features/reports/ReportList";
import { DeleteReportDialog } from "@/features/reports/DeleteReportDialog";
import { periodLabel } from "@/features/reports/presentation";
import { api } from "@/lib/api/client";

type ReportListItem = components["schemas"]["ReportListItem"];
const pageSize = 20;

export default function ReportsPage() {
  const [reports, setReports] = useState<ReportListItem[]>([]);
  const [deleted, setDeleted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [target, setTarget] = useState<ReportListItem | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setReports([]);
    setError(null);
    setActionError(null);
    api.listReports(undefined, pageSize, 0, deleted)
      .then((items) => { if (!cancelled) { setReports(items); setHasMore(items.length === pageSize); } })
      .catch((reason: unknown) => { if (!cancelled) setError(reason instanceof Error ? reason.message : "无法加载报告"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [deleted]);

  async function changeReport(report: ReportListItem, remove: boolean) {
    setBusy(true);
    setActionError(null);
    try {
      await (remove ? api.deleteReport(report.report_id) : api.restoreReport(report.report_id));
      setReports((items) => items.filter((item) => item.report_id !== report.report_id));
      setTarget(null);
      setNotice(remove ? "报告已删除，可在“已删除”中恢复。" : "报告已恢复，可在历史报告中查看。");
    } catch (reason: unknown) {
      setActionError(reason instanceof Error ? reason.message : "操作失败，请重试");
    } finally { setBusy(false); }
  }

  async function loadMore() {
    setBusy(true);
    setActionError(null);
    try {
      const items = await api.listReports(undefined, pageSize, reports.length, deleted);
      setReports((previous) => [...new Map([...previous, ...items].map((item) => [item.report_id, item])).values()]);
      setHasMore(items.length === pageSize);
    } catch (reason: unknown) { setActionError(reason instanceof Error ? reason.message : "无法加载更多报告"); }
    finally { setBusy(false); }
  }

  return <main className="min-h-screen bg-slate-50">
    <div className="mx-auto max-w-5xl px-5 py-10 sm:px-8">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold text-slate-950">{deleted ? "已删除报告" : "历史报告"}</h1>
          <p className="mt-2 text-sm text-slate-500">{deleted ? "恢复报告后，可继续查看原有的消费分析。" : "查看消费趋势与分类明细，管理你的月度和年度报告。"}</p>
        </div>
        <div className="flex gap-3">
          <button disabled={busy || loading} onClick={() => { setDeleted(!deleted); setNotice(null); }} className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 disabled:opacity-50">{deleted ? "历史报告" : "已删除"}</button>
          <Link href="/" className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100">返回工作台</Link>
        </div>
      </header>
      {notice && <p role="status" className="mb-4 rounded-xl border border-cyan-200 bg-cyan-50 p-4 text-sm text-cyan-800">{notice}</p>}
      {actionError && !target && <p role="alert" className="mb-4 rounded-xl bg-red-50 p-4 text-sm text-red-700">{actionError}</p>}
      {loading && <div className="rounded-2xl border border-slate-200 bg-white p-8 text-slate-500">正在加载报告…</div>}
      {error && <div role="alert" className="rounded-2xl border border-red-200 bg-red-50 p-5 text-red-700">{error}</div>}
      {!loading && !error && reports.length === 0 && <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-12 text-center">
        <p className="font-semibold text-slate-800">{deleted ? "没有已删除的报告" : "还没有消费报告"}</p>
        {!deleted && <p className="mt-2 text-sm text-slate-500">回到工作台，告诉助理要生成哪个月份或年份的消费报告。</p>}
      </div>}
      {!loading && !error && reports.length > 0 && <ReportList reports={reports} deleted={deleted} busy={busy} onDelete={(report) => { setTarget(report); setActionError(null); }} onRestore={(report) => void changeReport(report, false)} />}
      {!loading && hasMore && <button disabled={busy} onClick={() => void loadMore()} className="mt-5 w-full rounded-lg border border-slate-200 bg-white py-3 text-sm font-semibold text-slate-600 disabled:opacity-50">{busy ? "正在加载…" : "加载更多"}</button>}
      {target && <DeleteReportDialog title={`${periodLabel(target.period)}消费报告`} busy={busy} error={actionError} onCancel={() => { setTarget(null); setActionError(null); }} onConfirm={() => void changeReport(target, true)} />}
    </div>
  </main>;
}
