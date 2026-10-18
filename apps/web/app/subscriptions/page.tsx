"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { components } from "@banking/api-client";
import { api, ApiError } from "@/lib/api/client";
import { SubscriptionSummaryCard } from "@/features/subscriptions/SubscriptionSummaryCard";


type Snapshot = components["schemas"]["SubscriptionAnalysisSnapshot"];

export default function SubscriptionsPage() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [needsConsent, setNeedsConsent] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.listSubscriptions(30).then(setSnapshot).catch((reason: unknown) => {
      if (reason instanceof ApiError && reason.status === 428) setNeedsConsent(true);
      else setError(reason instanceof Error ? reason.message : "无法加载订阅");
    });
  }, []);

  const active = snapshot?.subscriptions.filter((item) => item.status === "ACTIVE").length ?? 0;
  async function confirmRead() {
    setBusy(true); setError(null);
    try {
      await api.confirmSubscriptionRead();
      setSnapshot(await api.listSubscriptions(30));
      setNeedsConsent(false);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "读取失败"); }
    finally { setBusy(false); }
  }
  return (
    <main className="min-h-screen bg-slate-50">
      <div className="mx-auto max-w-6xl px-5 py-10 sm:px-8">
        <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-semibold text-cyan-700">查看订阅与续费安排</p>
            <h1 className="mt-1 text-3xl font-semibold text-slate-950">订阅管理</h1>
            <p className="mt-2 text-sm text-slate-500">查看费用、续费时间，按需取消或重新订阅。</p>
          </div>
          <Link href="/" className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700">返回工作台</Link>
        </header>
        {error && <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-red-700">{error}</div>}
        {needsConsent && <section className="rounded-xl border border-amber-200 bg-white p-6">
          <h2 className="font-semibold">确认查询订阅</h2>
          <p className="mt-2 text-sm text-slate-600">将读取本人订阅、扣费金额和续费安排。本次查询授权有效期为5分钟。</p>
          <button disabled={busy} onClick={() => void confirmRead()} className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm text-white">{busy ? "读取中…" : "确认读取订阅"}</button>
        </section>}
        {!snapshot && !error && !needsConsent && <div className="rounded-xl bg-white p-8 text-slate-500">正在加载…</div>}
        {snapshot && (
          <>
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-xl border bg-white p-4"><p className="text-xs text-slate-500">活跃订阅</p><p className="mt-2 text-2xl font-bold">{active}</p></div>
              <div className="rounded-xl border bg-white p-4"><p className="text-xs text-slate-500">月度成本</p>{snapshot.monthly_cost_by_currency.map((item) => <p key={item.currency} className="mt-2 text-lg font-bold">{item.amount_display}</p>)}</div>
              <div className="rounded-xl border bg-white p-4"><p className="text-xs text-slate-500">预计年度成本</p>{snapshot.annual_projected_cost_by_currency.map((item) => <p key={item.currency} className="mt-2 text-lg font-bold">{item.amount_display}</p>)}</div>
            </div>
            <div className="mt-4 rounded-xl border bg-white p-4 text-sm text-slate-700">
              <p className="font-semibold">即将续费：{snapshot.upcoming_renewals.length} 项</p>
              <p className="mt-1">价格变动：{snapshot.price_changes.length} 项</p>
            </div>
            <SubscriptionSummaryCard snapshot={snapshot} onCancelled={(item) => {
              setSnapshot(current => current ? { ...current, subscriptions: current.subscriptions.map(row => row.subscription_id === item.subscription_id ? item : row) } : current);
              setError(null);
              void api.listSubscriptions(30).then(setSnapshot).catch(() => setError("订阅已取消，费用汇总更新失败，请刷新页面。"));
            }} />
          </>
        )}
      </div>
    </main>
  );
}
