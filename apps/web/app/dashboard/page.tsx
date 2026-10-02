"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import type { components } from "@banking/api-client";
import { api } from "@/lib/api/client";
import { AccountResults } from "@/features/accounts/AccountResults";
import { SpendingDashboard } from "@/features/dashboard/SpendingDashboard";
import { SubscriptionSummaryCard } from "@/features/subscriptions/SubscriptionSummaryCard";
import { TransactionAnomalyCard } from "@/features/anomalies/TransactionAnomalyCard";
import { RiskBadge } from "@/features/workflows/RiskDetails";

export default function DashboardPage() {
  const [month, setMonth] = useState("2026-08");
  const [snapshot, setSnapshot] = useState<components["schemas"]["DashboardSnapshot"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const refresh = useCallback(async () => {
    setLoading(true); setError(null);
    try { setSnapshot(await api.getDashboard(month)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "金融总览加载失败"); }
    finally { setLoading(false); }
  }, [month]);
  useEffect(() => { void refresh(); }, [refresh]);
  return <main className="min-h-screen min-w-0 bg-slate-50">
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-6 sm:px-8 sm:py-10">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div><p className="text-xs font-semibold tracking-wider text-cyan-700">AI BANKING AGENT · v0.9.1</p><h1 className="mt-2 text-3xl font-semibold text-slate-950">金融总览</h1><p className="mt-2 text-sm text-slate-500">账户与消费事实由银行服务提供，金额按币种展示。</p></div>
        <nav className="flex flex-wrap gap-2 text-sm"><Link className="rounded-lg border bg-white px-3 py-2" href="/">对话工作台</Link><Link className="rounded-lg border bg-white px-3 py-2" href="/subscriptions">订阅总览</Link><Link className="rounded-lg border bg-white px-3 py-2" href="/reports">消费报告</Link></nav>
      </header>
      <div className="flex flex-wrap items-center gap-3 rounded-xl border bg-white p-3">
        <label className="text-sm" htmlFor="dashboard-month">消费月份</label><input id="dashboard-month" type="month" value={month} onChange={(event) => setMonth(event.target.value)} className="rounded border px-2 py-1 text-sm" />
        <button disabled={loading} onClick={() => void refresh()} className="rounded bg-slate-900 px-3 py-2 text-xs font-semibold text-white">{loading ? "正在刷新…" : "刷新银行事实"}</button>
        {snapshot && <><span className="text-xs text-slate-500">本页只读 <RiskBadge level={snapshot.risk_level} /></span><span className="text-xs text-slate-500">只读查询 · 截至 {snapshot.as_of}</span></>}
      </div>
      {error && <p role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}</p>}
      {!snapshot && loading && <p className="rounded-xl bg-white p-8 text-slate-500">正在读取银行事实…</p>}
      {snapshot && <>
        <section aria-label="账户 Dashboard"><h2 className="mb-3 text-lg font-semibold">账户与余额</h2><AccountResults results={snapshot.accounts} /></section>
        <SpendingDashboard spending={snapshot.spending} />
        <SubscriptionSummaryCard snapshot={snapshot.subscriptions} />
        <TransactionAnomalyCard snapshot={snapshot.anomalies} />
      </>}
    </div>
  </main>;
}
