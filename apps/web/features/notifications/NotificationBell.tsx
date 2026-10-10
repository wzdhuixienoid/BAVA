"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import type { components } from "@banking/api-client";
import { api } from "@/lib/api/client";

type Notification = components["schemas"]["Notification"];

export function NotificationBell() {
  const [items, setItems] = useState<Notification[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const pageCount = useRef(1);
  const container = useRef<HTMLDivElement>(null);
  const refresh = useCallback(async () => {
    try {
      const pages = await Promise.all(Array.from({ length: pageCount.current }, (_, index) => api.listNotifications(index * 100)));
      setItems(pages.flatMap((page) => page.items));
      setUnread(pages[0].unread_count); setHasMore(pages[pages.length - 1].has_more);
      setError(null); setLoaded(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "消息加载失败");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 5000);
    const focus = () => { void refresh(); };
    window.addEventListener("focus", focus);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", focus); };
  }, [refresh]);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  async function act(id: string, remove = false) {
    setBusy(id);
    try {
      if (remove) await api.deleteNotification(id); else await api.readNotification(id);
      await refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "操作失败"); }
    finally { setBusy(null); }
  }

  async function more() {
    setBusy("more");
    try {
      const inbox = await api.listNotifications(items.length);
      pageCount.current += 1;
      setItems((current) => [...current, ...inbox.items]);
      setUnread(inbox.unread_count); setHasMore(inbox.has_more); setError(null);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "消息加载失败"); }
    finally { setBusy(null); }
  }

  return (
    <div ref={container} className="relative shrink-0">
      <button type="button" aria-label={unread ? `消息提醒，${unread} 条未读` : "消息提醒"}
        aria-expanded={open} aria-controls="notification-inbox"
        onClick={() => { setOpen(!open); if (!open) void refresh(); }}
        className="relative rounded-lg p-2 text-slate-400 hover:bg-slate-800 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-400">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9Z" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M10 21h4" strokeLinecap="round" />
        </svg>
        {unread > 0 && <span data-testid="notification-unread-dot" className="absolute right-1.5 top-1.5 h-2.5 w-2.5 rounded-full border-2 border-slate-950 bg-red-500" />}
      </button>
      {open && <section id="notification-inbox" aria-label="消息提醒" className="fixed left-3 top-16 z-50 w-[calc(100vw-24px)] max-w-sm overflow-hidden rounded-xl border border-slate-200 bg-white text-slate-900 shadow-2xl md:left-5 md:top-20 md:w-96">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <h2 className="font-semibold">消息提醒 <span className="text-xs font-normal text-slate-500">{unread} 条未读</span></h2>
          <button aria-label="关闭消息提醒" onClick={() => setOpen(false)} className="rounded px-2 py-1 text-slate-500 hover:bg-slate-100">✕</button>
        </div>
        {error && <p role="alert" className="px-4 py-3 text-xs text-red-700">{error} <button onClick={() => void refresh()} className="underline">重试</button></p>}
        <div className="max-h-[min(65vh,520px)] overflow-y-auto overscroll-contain">
          {!loaded && !error && <p className="p-6 text-center text-sm text-slate-500">正在加载…</p>}
          {loaded && items.length === 0 && <p className="p-8 text-center text-sm text-slate-500">暂无消息提醒</p>}
          {items.map((item) => <article key={item.notification_id} className={`border-b p-4 last:border-0 ${item.read_at ? "bg-white" : "bg-cyan-50"}`}>
            <div className="flex items-start justify-between gap-3">
              <h3 className="text-sm font-semibold">{!item.read_at && <span className="mr-1 text-cyan-600">●</span>}{item.title}</h3>
              <button disabled={busy !== null} onClick={() => void act(item.notification_id, true)} className="shrink-0 text-xs text-slate-500 hover:text-red-700" aria-label={`删除消息：${item.title}`}>删除</button>
            </div>
            <p className="mt-2 text-xs leading-5 text-slate-600">{item.kind.startsWith("SUBSCRIPTION_") ? item.message.replace(/([\d,.]+) CNY/g, "¥$1").replace(/订阅与代扣总览/g, "订阅管理") : item.message}</p>
            <time className="mt-2 block text-[11px] text-slate-400">{new Date(item.created_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false })}</time>
            <div className="mt-2 flex gap-4 text-xs">
              {!item.read_at && <button disabled={busy !== null} className="font-semibold text-cyan-700" onClick={() => void act(item.notification_id)}>标为已读</button>}
              {item.kind === "WEALTH_RESULT" && <Link href="/wealth" onClick={() => setOpen(false)} className="text-cyan-700 underline">查看理财订单</Link>}
              {item.kind.startsWith("SUBSCRIPTION_") && <Link href="/subscriptions" onClick={() => { if (!item.read_at) void act(item.notification_id); setOpen(false); }} className="text-cyan-700 underline">查看订阅</Link>}
              {item.schedule_id && <Link href="/scheduled-transfers" onClick={() => { if (!item.read_at) void act(item.notification_id); setOpen(false); }} className="text-cyan-700 underline">查看转账</Link>}
            </div>
          </article>)}
          {hasMore && <button disabled={busy !== null} onClick={() => void more()} className="w-full p-3 text-sm text-cyan-700">加载更早消息</button>}
        </div>
      </section>}
    </div>
  );
}
