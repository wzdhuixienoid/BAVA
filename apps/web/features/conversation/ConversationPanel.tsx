"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { components } from "@banking/api-client";
import { api } from "@/lib/api/client";
import { subscribeToConversation } from "@/lib/events/sse";
import { MessageComposer } from "./MessageComposer";
import { MessageList } from "./MessageList";
import { SecurityStatusBanner } from "@/features/security/SecurityStatusBanner";

type ConversationDetail = components["schemas"]["ConversationDetail"];
type Task = components["schemas"]["Task"];
type ReportListItem = components["schemas"]["ReportListItem"];
type Workflow = components["schemas"]["Workflow"];
type SecurityStatus = components["schemas"]["SecurityStatus"];

async function loadReports(conversationId: string): Promise<ReportListItem[]> {
  const reports: ReportListItem[] = [];
  for (let offset = 0; ; offset += 100) {
    const page = await api.listReports(conversationId, 100, offset);
    reports.push(...page);
    if (page.length < 100) return reports;
  }
}

export function ConversationPanel({ conversationId, onDeleted, onUpdated }: { conversationId: string; onDeleted?: () => Promise<void>; onUpdated?: () => Promise<void> }) {
  const [conversation, setConversation] = useState<ConversationDetail | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [reports, setReports] = useState<ReportListItem[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [plans, setPlans] = useState<components["schemas"]["Plan"][]>([]);
  const [securityStatus, setSecurityStatus] = useState<SecurityStatus | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activityRevision, setActivityRevision] = useState(0);
  const requestVersion = useRef(0);
  const active = useRef(true);

  const refresh = useCallback(async () => {
    const version = ++requestVersion.current;
    try {
      const [nextConversation, nextTasks, nextReports, nextWorkflows, nextSecurityStatus, nextPlans] = await Promise.all([
        api.getConversation(conversationId),
        api.listTasks(conversationId),
        loadReports(conversationId),
        api.listWorkflows(conversationId),
        api.getSecurityStatus(),
        api.listPlans(conversationId),
      ]);
      if (!active.current || version !== requestVersion.current) return;
      setConversation(nextConversation);
      setTasks(nextTasks);
      setReports(nextReports);
      setWorkflows(nextWorkflows);
      setPlans(nextPlans);
      setSecurityStatus(nextSecurityStatus);
      setError(null);
    } catch (reason) {
      if (!active.current || version !== requestVersion.current) return;
      if (reason instanceof Error && reason.message.includes("404")) { await onDeleted?.(); return; }
      setError(reason instanceof Error ? reason.message : "无法加载服务器状态");
    }
  }, [conversationId, onDeleted]);

  useEffect(() => {
    active.current = true;
    void refresh();
    let refreshTimer: ReturnType<typeof setTimeout> | undefined;
    const scheduleRefresh = () => {
      if (refreshTimer !== undefined) return;
      refreshTimer = setTimeout(() => {
        refreshTimer = undefined;
        setActivityRevision((revision) => revision + 1);
        void refresh();
      }, 100);
    };
    const unsubscribe = subscribeToConversation(
      conversationId,
      (event) => {
        if (event.type === "conversation.deleted") void onDeleted?.();
        else {
          scheduleRefresh();
          if (event.type === "conversation.updated") void onUpdated?.();
        }
      },
      (nextConnected) => {
        setConnected(nextConnected);
        if (nextConnected) scheduleRefresh();
      },
    );
    return () => {
      active.current = false;
      requestVersion.current += 1;
      clearTimeout(refreshTimer);
      unsubscribe();
    };
  }, [conversationId, refresh, onDeleted, onUpdated]);

  async function send(content: string) {
    await api.postMessage(conversationId, content);
    await refresh();
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-slate-200 px-4 py-4 lg:px-6">
        <div className="min-w-0">
          <h2 className="truncate font-semibold">{conversation?.title ?? "正在加载对话…"}</h2>
          <p className="mt-1 text-xs text-slate-400">处理过程与结果都在对话中</p>
        </div>
        <span className={`shrink-0 text-[10px] font-medium lg:text-xs ${connected ? "text-emerald-600" : "text-amber-600"}`}>
          {connected ? "● 实时连接正常" : "○ 正在恢复实时连接"}
        </span>
      </header>
      {error && (
        <div role="alert" className="shrink-0 bg-red-50 px-4 py-2 text-xs text-red-700">{error} <button className="ml-2 underline" onClick={() => void refresh()}>重试</button></div>
      )}
      <div className="shrink-0"><SecurityStatusBanner status={securityStatus} /></div>
      <section aria-label="对话工作区" className="flex min-h-0 min-w-0 flex-1 flex-col">
        <MessageList messages={conversation?.messages ?? []} tasks={tasks} plans={plans} reports={reports} workflows={workflows} activityRevision={activityRevision} onRefresh={refresh} />
        <MessageComposer onSend={send} />
      </section>
    </div>
  );
}
