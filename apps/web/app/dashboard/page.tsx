"use client";

import Link from "next/link";
import { APP_VERSION } from "@/lib/version";
import { useCallback, useEffect, useRef, useState } from "react";
import type { components } from "@banking/api-client";
import { api } from "@/lib/api/client";
import { AccountResults } from "@/features/accounts/AccountResults";
import { SpendingDashboard } from "@/features/dashboard/SpendingDashboard";
import { RecentTransactions } from "@/features/dashboard/RecentTransactions";
import { TransactionAnomalyCard } from "@/features/anomalies/TransactionAnomalyCard";
import { RiskBadge } from "@/features/workflows/RiskDetails";
import { currentMonth, queryTime } from "@/lib/presentation/time";

export default function DashboardPage() {
  const [month, setMonth] = useState(currentMonth);
  const [availableMonths, setAvailableMonths] = useState<string[]>([]);
  const years = [...new Set([currentMonth().slice(0, 4), month.slice(0, 4), ...availableMonths.map(value => value.slice(0, 4))])].sort().reverse();
  const requestVersion = useRef(0);
  const [snapshot, setSnapshot] = useState<components["schemas"]["DashboardSnapshot"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const refresh = useCallback(async () => {
    const version = ++requestVersion.current;
    setLoading(true); setError(null);
    try { const next = await api.getDashboard(month); if (version === requestVersion.current) setSnapshot(next); }
    catch (reason) { if (version === requestVersion.current) setError(reason instanceof Error ? reason.message : "金融总览加载失败"); }
    finally { if (version === requestVersion.current) setLoading(false); }
  }, [month]);
  useEffect(() => { void refresh(); }, [refresh]);
  return <main className="min-h-screen min-w-0 bg-slate-50">
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-6 sm:px-8 sm:py-10">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div><p className="text-xs font-semibold tracking-wider text-cyan-700">AI BANKING AGENT · v{APP_VERSION}</p><h1 className="mt-2 text-3xl font-semibold text-slate-950">金融总览</h1><p className="mt-2 text-sm text-slate-500">账户与账单事实由银行服务提供，金额按币种展示。</p></div>
        <nav aria-label="金融服务" className="flex flex-wrap gap-2 text-sm"><Link className="rounded-lg border bg-white px-3 py-2" href="/">对话工作台</Link></nav>
      </header>
      {error && <p role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}</p>}
      {!snapshot && loading && <p className="rounded-xl bg-white p-8 text-slate-500">正在读取银行事实…</p>}
      {snapshot && <>
        <section aria-label="账户 Dashboard"><h2 className="mb-3 text-lg font-semibold">账户与余额</h2><AccountResults results={snapshot.accounts} /></section>
        <RecentTransactions transactions={snapshot.recent_transactions ?? []} accountNames={Object.fromEntries(snapshot.accounts.map(account => [account.account_id, account.display_name]))} refreshKey={snapshot.as_of} onAvailableMonths={setAvailableMonths} />
      </>}
      <div aria-label="消费查询" className="flex flex-wrap items-center gap-3 rounded-xl border bg-white p-3">
        <label className="flex items-center gap-2 text-sm" htmlFor="dashboard-year">消费年份<select id="dashboard-year" value={month.slice(0, 4)} onChange={event => setMonth(`${event.target.value}-${month.slice(5, 7)}`)} className="rounded border bg-white px-2 py-1 text-sm">{years.map(year => <option key={year} value={year}>{year}年</option>)}</select></label>
        <label className="flex items-center gap-2 text-sm" htmlFor="dashboard-month">消费月份<select id="dashboard-month" value={month.slice(5, 7)} onChange={event => setMonth(`${month.slice(0, 4)}-${event.target.value}`)} className="rounded border bg-white px-2 py-1 text-sm">{Array.from({ length: 12 }, (_, index) => <option key={index + 1} value={String(index + 1).padStart(2, "0")}>{index + 1}月</option>)}</select></label>
        <button disabled={loading} onClick={() => void refresh()} className="rounded bg-slate-900 px-3 py-2 text-xs font-semibold text-white">{loading ? "正在刷新…" : "刷新银行事实"}</button>
        {snapshot && <><span className="text-xs text-slate-500">本页只读 <RiskBadge level={snapshot.risk_level} /></span><span className="text-xs text-slate-500">只读查询 · 截至 {queryTime(snapshot.as_of)}</span></>}
      </div>
      {snapshot && <>
        <SpendingDashboard spending={snapshot.spending} />
        <TransactionAnomalyCard snapshot={snapshot.anomalies} />
      </>}
    </div>
  </main>;
}
