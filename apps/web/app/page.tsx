"use client";

import { useCallback, useEffect, useState } from "react";
import type { components } from "@banking/api-client";
import { ConversationPanel } from "@/features/conversation/ConversationPanel";
import { api } from "@/lib/api/client";

type Conversation = components["schemas"]["Conversation"];

export default function HomePage() {
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
    <main className="mx-auto grid min-h-screen max-w-[1440px] grid-cols-1 bg-white shadow-sm md:grid-cols-[280px_1fr]">
      <aside className="border-b border-slate-200 bg-slate-950 p-5 text-white md:border-b-0 md:border-r">
        <div className="mb-6">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">迭代 0</p>
          <h1 className="mt-2 text-xl font-semibold">银行助理工作台</h1>
        </div>
        <button
          className="mb-5 w-full rounded-lg bg-cyan-400 px-4 py-2.5 font-semibold text-slate-950 hover:bg-cyan-300"
          onClick={createConversation}
        >
          + 新建对话
        </button>
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
      <section className="min-w-0">
        {selectedId ? (
          <ConversationPanel conversationId={selectedId} />
        ) : (
          <div className="grid min-h-screen place-items-center p-8 text-center text-slate-500">
            新建一个对话，开始验证消息 → 任务 → 事件的启动流程。
          </div>
        )}
      </section>
    </main>
  );
}
