"use client";

import { useCallback, useEffect, useState } from "react";
import type { components } from "@banking/api-client";
import Link from "next/link";
import { ConversationPanel } from "@/features/conversation/ConversationPanel";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/AuthProvider";

type Conversation = components["schemas"]["Conversation"];

export default function HomePage() {
  const auth = useAuth();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const items = await api.listConversations();
    setConversations(items);
    setSelectedId((current) => current ?? items[0]?.conversation_id ?? null);
  }, []);

  useEffect(() => {
    refresh().finally(() => setLoading(false));
  }, [refresh]);

  async function createConversation() {
    const conversation = await api.createConversation({ title: "新对话" });
    await refresh();
    setSelectedId(conversation.conversation_id);
  }

  return (
    <main className="mx-auto grid h-dvh min-h-0 max-w-[1600px] grid-cols-1 grid-rows-[160px_minmax(0,1fr)] overflow-hidden bg-white shadow-sm md:grid-cols-[260px_minmax(0,1fr)] md:grid-rows-[minmax(0,1fr)]">
      <aside aria-label="对话导航" className="min-h-0 overflow-y-auto overscroll-contain border-b border-slate-200 bg-slate-950 p-5 text-white md:border-b-0 md:border-r">
        <div className="mb-6">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">
            智能银行服务
          </p>
          <h1 className="mt-2 text-xl font-semibold">银行助理工作台</h1>
          <p className="mt-1 text-xs text-slate-400">v0.9.2 · 审计链、安全自评与 Demo Hardening</p>
        </div>
        <button
          className="mb-5 w-full rounded-lg bg-cyan-400 px-4 py-2.5 font-semibold text-slate-950 hover:bg-cyan-300"
          onClick={createConversation}
        >
          + 新建对话
        </button>
        <Link
          href="/dashboard"
          className="mb-3 block rounded-lg bg-slate-800 px-4 py-2.5 text-center text-sm font-semibold text-cyan-100 hover:bg-slate-700"
        >金融总览 Dashboard</Link>
        <Link
          href="/reports"
          className="mb-6 block w-full rounded-lg border border-slate-700 px-4 py-2.5 text-center text-sm font-semibold text-slate-200 hover:bg-slate-900"
        >
          查看历史报告
        </Link>
        <Link
          href="/subscriptions"
          className="mb-6 block w-full rounded-lg border border-cyan-700 px-4 py-2.5 text-center text-sm font-semibold text-cyan-100 hover:bg-slate-900"
        >
          订阅与代扣总览
        </Link>
        <div className="mb-6 rounded-lg border border-slate-800 px-3 py-2 text-xs text-slate-400">
          <span>{auth.development ? "Development Principal" : "OIDC 已认证"}</span>
          {!auth.development && (
            <button className="ml-3 text-cyan-300 hover:text-cyan-200" onClick={() => void auth.logout()}>
              登出
            </button>
          )}
        </div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">最近对话</p>
        <nav className="space-y-2">
          {loading && <p className="text-sm text-slate-400">加载中…</p>}
          {conversations.map((conversation) => (
            <button
              key={conversation.conversation_id}
              onClick={() => setSelectedId(conversation.conversation_id)}
              className={`w-full rounded-lg px-3 py-3 text-left text-sm transition ${
                selectedId === conversation.conversation_id
                  ? "bg-slate-800 text-white"
                  : "text-slate-300 hover:bg-slate-900"
              }`}
            >
              <span className="block truncate font-medium">{conversation.title}</span>
              <span className="mt-1 block truncate text-xs text-slate-500">
                {conversation.conversation_id}
              </span>
            </button>
          ))}
        </nav>
      </aside>
      <section className="min-h-0 min-w-0 overflow-hidden">
        {selectedId ? (
          <ConversationPanel key={selectedId} conversationId={selectedId} />
        ) : (
          <div className="grid h-full place-items-center p-8 text-center text-slate-500">
            新建一个对话，查询账户、分析消费或管理订阅。
          </div>
        )}
      </section>
    </main>
  );
}
