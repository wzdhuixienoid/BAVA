"use client";

import { FormEvent, useState } from "react";

export function MessageComposer({ onSend }: { onSend: (content: string) => Promise<void> }) {
  const [content, setContent] = useState("");
  const [sending, setSending] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const value = content.trim();
    if (!value || sending) return;
    setSending(true);
    try {
      await onSend(value);
      setContent("");
    } finally {
      setSending(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex gap-3 border-t border-slate-200 p-4">
      <input
        aria-label="Message"
        value={content}
        onChange={(event) => setContent(event.target.value)}
        placeholder="Type a message…"
        className="min-w-0 flex-1 rounded-lg border border-slate-300 px-4 py-3 outline-none ring-cyan-500 focus:ring-2"
      />
      <button
        disabled={!content.trim() || sending}
        className="rounded-lg bg-slate-900 px-5 py-3 font-semibold text-white hover:bg-slate-800"
      >
        {sending ? "Sending…" : "Send"}
      </button>
    </form>
  );
}

