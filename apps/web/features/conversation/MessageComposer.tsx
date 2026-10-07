"use client";

import { FormEvent, useEffect, useState } from "react";
import { consumeSubscriptionPrefill } from "./subscription-prefill";

export function MessageComposer({ onSend }: { onSend: (content: string) => Promise<void> }) {
  const [content, setContent] = useState("");
  useEffect(() => {
    const prefill = consumeSubscriptionPrefill(window.location.href, window.history);
    if (prefill !== null) setContent(prefill);
  }, []);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const value = content.trim();
    if (!value || sending) return;
    setSending(true);
    setError(null);
    try {
      await onSend(value);
      setContent("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "消息发送失败，请重试。");
    } finally {
      setSending(false);
    }
  }

  return (
    <form onSubmit={submit} className="shrink-0 border-t border-slate-200 bg-white p-4">
      {error && <p role="alert" className="mb-2 text-xs text-red-700">{error}</p>}
      <div className="flex gap-3">
      <input
        aria-label="消息"
        value={content}
        onChange={(event) => setContent(event.target.value)}
        placeholder="输入消息…"
        className="min-w-0 flex-1 rounded-lg border border-slate-300 px-4 py-3 outline-none ring-cyan-500 focus:ring-2"
      />
      <button
        disabled={!content.trim() || sending}
        className="rounded-lg bg-slate-900 px-5 py-3 font-semibold text-white hover:bg-slate-800"
      >
        {sending ? "发送中…" : "发送"}
      </button>
      </div>
    </form>
  );
}
