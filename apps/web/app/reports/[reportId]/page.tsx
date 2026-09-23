"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { components } from "@banking/api-client";
import { MonthlyReportView } from "@/features/reports/MonthlyReportView";
import { api } from "@/lib/api/client";

type ReportResponse = components["schemas"]["ReportResponse"];

export default function ReportDetailPage() {
  const params = useParams<{ reportId: string }>();
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getReport(params.reportId)
      .then((item) => {
        setReport(item);
        setError(null);
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "无法加载报告");
      });
  }, [params.reportId]);

  return (
    <main className="min-h-screen bg-slate-50">
      <div className="mx-auto max-w-6xl px-5 py-8 sm:px-8">
        <nav className="mb-6 flex gap-4 text-sm font-semibold">
          <Link href="/reports" className="text-cyan-700 hover:text-cyan-600">← 历史报告</Link>
          <Link href="/" className="text-slate-500 hover:text-slate-800">工作台</Link>
        </nav>
        {!report && !error && <div className="rounded-2xl border border-slate-200 bg-white p-8 text-slate-500">正在加载报告…</div>}
        {error && <div className="rounded-2xl border border-red-200 bg-red-50 p-5 text-red-700">{error}</div>}
        {report && <MonthlyReportView report={report} />}
      </div>
    </main>
  );
}
