import Link from "next/link";
import type { components } from "@banking/api-client";
import { dateTimeLabel, periodLabel } from "./presentation";

type ReportListItem = components["schemas"]["ReportListItem"];

export function ReportList({ reports }: { reports: ReportListItem[] }) {
  return (
    <div className="grid gap-4">
      {reports.map((report) => (
        <Link
          key={report.report_id}
          href={`/reports/${report.report_id}`}
          className="group rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:border-cyan-300 hover:shadow-md"
        >
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-cyan-700">{report?.period.length === 4 ? "年度消费报告" : "月度消费报告"}</p>
              <h2 className="mt-1 text-lg font-semibold text-slate-950">{periodLabel(report.period)}消费报告</h2>
              <p className="mt-2 text-sm text-slate-600">{report.headline}</p>
              <p className="mt-3 text-xs text-slate-400">{dateTimeLabel(report.created_at)}</p>
            </div>
            <div className="text-right">
              <p className="text-xs text-slate-500">总支出</p>
              <p className="mt-1 text-2xl font-semibold text-slate-950">{report.total_spending_display}</p>
              <span className="mt-3 inline-block text-sm font-semibold text-cyan-700 group-hover:text-cyan-600">查看报告 →</span>
            </div>
          </div>
        </Link>
      ))}
    </div>
  );
}
