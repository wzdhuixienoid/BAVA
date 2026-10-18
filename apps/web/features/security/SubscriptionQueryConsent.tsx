"use client";

import { useState } from "react";
import { api } from "@/lib/api/client";

export function SubscriptionQueryConsent({ conversationId, content, onRefresh }: {
  conversationId: string; content: string; onRefresh: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [confirmed, setConfirmed] = useState(false);
  async function confirm() {
    setBusy(true); setError(undefined);
    try {
      await api.confirmSubscriptionRead();
      await api.postMessage(conversationId, content);
      setConfirmed(true);
      await onRefresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "确认失败"); }
    finally { setBusy(false); }
  }
  return <section className="rounded-xl border border-amber-200 bg-amber-50 p-4">
    <p>查询订阅、费用和续费安排需要你的确认。查询授权有效期为5分钟。</p>
    <button disabled={busy || confirmed} onClick={() => void confirm()} className="mt-3 rounded bg-slate-900 px-4 py-2 text-white">{confirmed ? "已确认，正在查询" : busy ? "处理中…" : "确认读取订阅"}</button>
    {error && <p role="alert" className="mt-2 text-red-700">{error}</p>}
  </section>;
}
