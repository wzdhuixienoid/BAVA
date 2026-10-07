"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { components } from "@banking/api-client";
import Link from "next/link";
import { ConversationPanel } from "@/features/conversation/ConversationPanel";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/AuthProvider";

type Conversation = components["schemas"]["Conversation"];

export default function HomePage() {
  const auth = useAuth();
  const initialized = useRef(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Conversation | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [renameTarget, setRenameTarget] = useState<Conversation | null>(null);
  const [renameTitle, setRenameTitle] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);
  const [renaming, setRenaming] = useState(false);

  const refresh = useCallback(async () => {
    const items = await api.listConversations();
    setConversations(items);
    const requestedId = new URLSearchParams(window.location.search).get("conversation");
    setSelectedId((current) => items.some((item) => item.conversation_id === current) ? current : items.find((item) => item.conversation_id === requestedId)?.conversation_id ?? items[0]?.conversation_id ?? null);
  }, []);

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    void refresh().then(async () => {
      const params = new URLSearchParams(window.location.search);
      if ((params.has("cancel") || params.has("resume")) && (await api.listConversations()).length === 0) {
        const created = await api.createConversation({ title: "订阅管理" });
        await refresh(); setSelectedId(created.conversation_id);
      }
    }).catch((reason: unknown) => setDeleteError(reason instanceof Error ? reason.message : "无法加载对话列表")).finally(() => setLoading(false));
  }, [refresh]);

  useEffect(() => {
    const channel = new BroadcastChannel("banking-conversations");
    const reload = () => { void refresh().catch((reason: Error) => setDeleteError(reason.message)); };
    channel.onmessage = reload;
    window.addEventListener("focus", reload);
    return () => { channel.close(); window.removeEventListener("focus", reload); };
  }, [refresh]);

  async function deleteConversation(conversation: Conversation) {
    setDeleting(conversation.conversation_id); setDeleteError(null);
    try { await api.deleteConversation(conversation.conversation_id); const channel = new BroadcastChannel("banking-conversations"); channel.postMessage("deleted"); channel.close(); await refresh(); setDeleteTarget(null); }
    catch (reason) { setDeleteError(reason instanceof Error ? reason.message : "删除失败，请重试"); }
    finally { setDeleting(null); }
  }

  async function createConversation() {
    const conversation = await api.createConversation({ title: "新对话" });
    await refresh();
    setSelectedId(conversation.conversation_id);
  }

  async function renameConversation(event: React.FormEvent) {
    event.preventDefault();
    if (!renameTarget || !renameTitle.trim() || renaming) return;
    setRenaming(true); setRenameError(null);
    try {
      await api.renameConversation(renameTarget.conversation_id, renameTitle.trim());
      const channel = new BroadcastChannel("banking-conversations");
      channel.postMessage("renamed"); channel.close();
      await refresh(); setRenameTarget(null);
    } catch (reason) {
      setRenameError(reason instanceof Error ? reason.message : "修改名称失败，请重试");
    } finally { setRenaming(false); }
  }

  return (
    <main className="mx-auto grid h-dvh min-h-0 max-w-[1600px] grid-cols-1 grid-rows-[160px_minmax(0,1fr)] overflow-hidden bg-white shadow-sm md:grid-cols-[260px_minmax(0,1fr)] md:grid-rows-[minmax(0,1fr)]">
      <aside aria-label="对话导航" className="min-h-0 overflow-y-auto overscroll-contain border-b border-slate-200 bg-slate-950 p-5 text-white md:border-b-0 md:border-r">
        <div className="mb-6">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">
            智能银行服务
          </p>
          <h1 className="mt-2 text-xl font-semibold">银行助理工作台</h1>
          <p className="mt-1 text-xs text-slate-400">v0.9.3 · 对话、收款人与订阅管理</p>
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
        {!auth.development && <button className="mb-5 text-sm text-cyan-300 hover:text-cyan-200" onClick={() => void auth.logout()}>登出</button>}
        <Link href="/payees" className="mb-5 block rounded-lg border border-slate-700 px-4 py-2.5 text-center text-sm">收款人管理</Link>
        {deleteError && <p role="alert" className="mb-3 text-xs text-red-300">{deleteError}</p>}
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">最近对话</p>
        <nav className="space-y-2">
          {loading && <p className="text-sm text-slate-400">加载中…</p>}
          {conversations.map((conversation) => (
            <div key={conversation.conversation_id} className="flex items-center gap-1">
            <button
              onClick={() => setSelectedId(conversation.conversation_id)}
              className={`min-w-0 flex-1 rounded-lg px-3 py-3 text-left text-sm transition ${
                selectedId === conversation.conversation_id
                  ? "bg-slate-800 text-white"
                  : "text-slate-300 hover:bg-slate-900"
              }`}
            >
              <span className="block truncate font-medium">{conversation.title}</span>
            </button>
            <button aria-label={`重命名对话：${conversation.title}`} onClick={() => {
              setRenameTarget(conversation); setRenameTitle(conversation.title); setRenameError(null);
            }} className="shrink-0 rounded px-1.5 py-3 text-xs text-slate-400 hover:bg-slate-800 hover:text-cyan-300">改名</button>
            <button aria-label={`删除对话：${conversation.title}`} disabled={deleting !== null} onClick={() => { setDeleteError(null); setDeleteTarget(conversation); }} className="shrink-0 rounded px-2 py-3 text-xs text-slate-400 hover:bg-slate-800 hover:text-red-300">{deleting === conversation.conversation_id ? "…" : "删除"}</button>
            </div>
          ))}
        </nav>
      </aside>
      {renameTarget && <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 p-5">
        <form onSubmit={renameConversation} role="dialog" aria-modal="true" aria-labelledby="rename-title" className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
          <h2 id="rename-title" className="text-lg font-semibold">修改对话名称</h2>
          <label className="mt-4 block text-sm" htmlFor="conversation-title">对话名称</label>
          <input id="conversation-title" autoFocus maxLength={100} value={renameTitle} disabled={renaming} onChange={(event) => setRenameTitle(event.target.value)} className="mt-2 w-full rounded-lg border px-3 py-2" />
          {renameError && <p role="alert" className="mt-3 text-sm text-red-700">{renameError}</p>}
          <div className="mt-5 flex justify-end gap-3">
            <button type="button" disabled={renaming} onClick={() => setRenameTarget(null)} className="rounded-lg border px-4 py-2">取消</button>
            <button disabled={renaming || !renameTitle.trim()} className="rounded-lg bg-slate-900 px-4 py-2 text-white">{renaming ? "保存中…" : "保存名称"}</button>
          </div>
        </form>
      </div>}
      {deleteTarget && <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 p-5">
        <div role="dialog" aria-modal="true" aria-labelledby="delete-title" className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
          <h2 id="delete-title" className="text-lg font-semibold">删除对话</h2><p className="mt-3 text-sm text-slate-600">确认删除“{deleteTarget.title}”？业务及审计记录会保留。</p>
          {deleteError && <p role="alert" className="mt-3 text-sm text-red-700">{deleteError}</p>}
          <div className="mt-5 flex justify-end gap-3"><button autoFocus disabled={deleting !== null} onClick={() => setDeleteTarget(null)} className="rounded-lg border px-4 py-2">返回</button><button disabled={deleting !== null} onClick={() => void deleteConversation(deleteTarget)} className="rounded-lg bg-red-700 px-4 py-2 text-white">{deleting ? "删除中…" : "确认删除"}</button></div>
        </div>
      </div>}
      <section className="min-h-0 min-w-0 overflow-hidden">
        {selectedId ? (
          <ConversationPanel key={selectedId} conversationId={selectedId} onDeleted={refresh} onUpdated={refresh} />
        ) : (
          <div className="grid h-full place-items-center p-8 text-center text-slate-500">
            新建一个对话，查询账户、分析消费或管理订阅。
          </div>
        )}
      </section>
    </main>
  );
}
