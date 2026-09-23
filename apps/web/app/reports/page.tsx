"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { components } from "@banking/api-client";
import { ReportList } from "@/features/reports/ReportList";
import { api } from "@/lib/api/client";

type ReportListItem = components["schemas"]["ReportListItem"];

export default function ReportsPage() {
  const [reports, setReports] = useState<ReportListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listReports()
      .then((items) => {
        setReports(items);
        setError(null);
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "无法加载报告");
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="min-h-screen bg-slate-50">
      <div className="mx-auto max-w-5xl px-5 py-10 sm:px-8">
        <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-semibold text-cyan-700">只读银行助理</p>
            <h1 className="mt-1 text-3xl font-semibold text-slate-950">历史报告</h1>
            <p className="mt-2 text-sm text-slate-500">已持久化的报告不会因模型或格式器升级而变化。</p>
          </div>
          <Link href="/" className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100">
            返回工作台
          </Link>
        </header>
        {loading && <div className="rounded-2xl border border-slate-200 bg-white p-8 text-slate-500">正在加载报告…</div>}
        {error && <div className="rounded-2xl border border-red-200 bg-red-50 p-5 text-red-700">{error}</div>}
        {!loading && !error && reports.length === 0 && (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-12 text-center">
            <p className="font-semibold text-slate-800">还没有月度消费报告</p>
            <p className="mt-2 text-sm text-slate-500">回到工作台输入“生成一份二〇二六年八月消费报告”。</p>
          </div>
        )}
        {!loading && !error && reports.length > 0 && <ReportList reports={reports} />}
      </div>
    </main>
  );
}
