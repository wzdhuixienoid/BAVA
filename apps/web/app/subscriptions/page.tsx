"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { components } from "@banking/api-client";
import { api } from "@/lib/api/client";
import { SubscriptionSummaryCard } from "@/features/subscriptions/SubscriptionSummaryCard";


type Snapshot = components["schemas"]["SubscriptionAnalysisSnapshot"];

export default function SubscriptionsPage() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listSubscriptions(30).then(setSnapshot).catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : "无法加载订阅");
    });
  }, []);

  const active = snapshot?.subscriptions.filter((item) => item.status === "ACTIVE").length ?? 0;
  return (
    <main className="min-h-screen bg-slate-50">
      <div className="mx-auto max-w-6xl px-5 py-10 sm:px-8">
        <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-semibold text-cyan-700">确定性周期扣费分析</p>
            <h1 className="mt-1 text-3xl font-semibold text-slate-950">订阅与代扣</h1>
            <p className="mt-2 text-sm text-slate-500">多币种分组展示，不做汇率换算。</p>
          </div>
          <Link href="/" className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700">返回工作台</Link>
        </header>
        {error && <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-red-700">{error}</div>}
        {!snapshot && !error && <div className="rounded-xl bg-white p-8 text-slate-500">正在加载…</div>}
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
            <SubscriptionSummaryCard snapshot={snapshot} />
          </>
        )}
      </div>
    </main>
  );
}
