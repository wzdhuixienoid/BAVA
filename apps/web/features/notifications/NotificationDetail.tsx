"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { components } from "@banking/api-client";
import { TransactionAnomalyCard } from "@/features/anomalies/TransactionAnomalyCard";
import { api } from "@/lib/api/client";
import { queryTime } from "@/lib/presentation/time";

type Notification = components["schemas"]["Notification"];

export function NotificationDetail({ notificationId }: { notificationId: string }) {
  const [item, setItem] = useState<Notification | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setItem(null); setError("");
    void api.getNotification(notificationId).then(value => {
      if (active) setItem(value);
    }).catch(reason => {
      if (active) setError(reason instanceof Error ? reason.message : "无法读取提醒");
    });
    return () => { active = false; };
  }, [notificationId]);

  return (
    <main className="min-h-screen min-w-0 bg-slate-50">
      <div className="mx-auto max-w-6xl space-y-6 px-4 py-6 sm:px-8 sm:py-10">
        <nav className="flex flex-wrap gap-4 text-sm font-semibold">
          <Link href="/" className="text-cyan-700 hover:text-cyan-600">← 返回工作台</Link>
          <Link href="/dashboard" className="text-slate-500 hover:text-slate-800">查看金融总览</Link>
        </nav>
        {error && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-5 text-red-700">{error}</p>}
        {!item && !error && <p role="status" className="rounded-xl border bg-white p-6 text-slate-500">正在读取提醒…</p>}
        {item && <>
          <header className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h1 className="text-2xl font-semibold text-slate-950">{item.title}</h1>
            <p className="mt-3 text-sm leading-7 text-slate-700">{item.message}</p>
            <p className="mt-3 text-xs text-slate-500">提醒生成时间：{queryTime(item.created_at)}（北京时间）</p>
          </header>
          {item.anomaly_snapshot && <>
            <p className="text-sm text-slate-500">以下保留提醒生成时的交易与规则依据。查看最新记录可进入金融总览。</p>
            <TransactionAnomalyCard snapshot={item.anomaly_snapshot} />
          </>}
        </>}
      </div>
    </main>
  );
}
