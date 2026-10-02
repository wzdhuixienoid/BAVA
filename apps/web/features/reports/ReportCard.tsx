import Link from "next/link";
import type { components } from "@banking/api-client";
import { periodLabel } from "./presentation";

type Task = components["schemas"]["Task"];
type ReportListItem = components["schemas"]["ReportListItem"];

function outputReportId(task?: Task): string | null {
  const value = task?.output?.report_id;
  return typeof value === "string" ? value : null;
}

export function ReportCard({ task, report }: { task?: Task; report?: ReportListItem }) {
  const reportId = report?.report_id ?? outputReportId(task);
  if (!reportId) return null;

  return (
    <section aria-label="消费报告" className="rounded-xl border border-cyan-200 bg-cyan-50/60 p-4">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-cyan-700">
        月度消费报告
      </p>
      <p className="mt-1 text-sm font-semibold text-slate-900">
        {report ? `${periodLabel(report.period)}消费报告` : "报告已生成"}
      </p>
      {report && <p className="mt-1 text-xl font-semibold text-slate-950">{report.total_spending_display}</p>}
      {report && <p className="mt-2 text-sm leading-relaxed text-slate-600">{report.headline}</p>}
      <Link
        href={`/reports/${encodeURIComponent(reportId)}`}
        className="mt-3 inline-flex rounded-md bg-slate-950 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800"
      >
        查看报告
      </Link>
    </section>
  );
}
