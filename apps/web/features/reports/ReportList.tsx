import Link from "next/link";
import type { components } from "@banking/api-client";
import { dateTimeLabel, periodLabel } from "./presentation";

type ReportListItem = components["schemas"]["ReportListItem"];

export function ReportList({ reports, deleted = false, busy = false, onDelete, onRestore }: {
  reports: ReportListItem[];
  deleted?: boolean;
  busy?: boolean;
  onDelete?: (report: ReportListItem) => void;
  onRestore?: (report: ReportListItem) => void;
}) {
  return (
    <div className="grid gap-4">
      {reports.map((report) => {
        const title = `${periodLabel(report.period)}消费报告`;
        return <article key={report.report_id} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <p className="text-xs font-semibold text-cyan-700">{report.period.length === 4 ? "年度消费报告" : "月度消费报告"}</p>
              <h2 className="mt-1 text-lg font-semibold text-slate-950">
                {deleted ? title : <Link href={`/reports/${report.report_id}`} className="hover:text-cyan-700">{title}</Link>}
              </h2>
              <p className="mt-2 text-sm text-slate-600">{report.headline}</p>
              <p className="mt-3 text-xs text-slate-400">{deleted ? "删除于" : "生成于"} {dateTimeLabel(deleted && report.deleted_at ? report.deleted_at : report.created_at)}</p>
            </div>
            <div className="text-right">
              <p className="text-xs text-slate-500">总支出</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums text-slate-950">{report.total_spending_display}</p>
              <div className="mt-4 flex items-center justify-end gap-4 text-sm font-semibold">
                {deleted ? <button disabled={busy} onClick={() => onRestore?.(report)} className="rounded-md border border-cyan-200 px-3 py-1.5 text-cyan-700 hover:bg-cyan-50 disabled:opacity-50" aria-label={`恢复${title}`}>恢复报告</button> : <>
                  <Link href={`/reports/${report.report_id}`} className="text-cyan-700 hover:text-cyan-600">查看报告 →</Link>
                  {onDelete && <button disabled={busy} onClick={() => onDelete(report)} className="rounded-md px-2 py-1.5 text-slate-400 hover:bg-red-50 hover:text-red-700 disabled:opacity-50" aria-label={`删除${title}`}>删除</button>}
                </>}
              </div>
            </div>
          </div>
        </article>;
      })}
    </div>
  );
}
