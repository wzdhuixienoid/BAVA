"use client";

import { useCallback, useEffect, useState } from "react";
import type { components } from "@banking/api-client";
import { api } from "@/lib/api/client";
import { subscribeToConversation } from "@/lib/events/sse";
import { MessageComposer } from "./MessageComposer";
import { MessageList } from "./MessageList";
import { TaskPanel } from "@/features/tasks/TaskPanel";

type ConversationDetail = components["schemas"]["ConversationDetail"];
type Task = components["schemas"]["Task"];

export function ConversationPanel({ conversationId }: { conversationId: string }) {
  const [conversation, setConversation] = useState<ConversationDetail | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [nextConversation, nextTasks] = await Promise.all([
        api.getConversation(conversationId),
        api.listTasks(conversationId),
      ]);
      setConversation(nextConversation);
      setTasks(nextTasks);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load server state");
    }
  }, [conversationId]);

  useEffect(() => {
    setConversation(null);
    setTasks([]);
    void refresh();
    return subscribeToConversation(
      conversationId,
      () => void refresh(),
      setConnected,
    );
  }, [conversationId, refresh]);

  async function send(content: string) {
    await api.postMessage(conversationId, content);
    await refresh();
  }

  return (
    <div className="grid min-h-screen grid-rows-[auto_1fr]">
      <header className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
        <div>
          <h2 className="font-semibold">{conversation?.title ?? "Loading conversation…"}</h2>
          <p className="mt-1 font-mono text-[10px] text-slate-400">{conversationId}</p>
        </div>
        <span className={`text-xs font-medium ${connected ? "text-emerald-600" : "text-amber-600"}`}>
          {connected ? "● SSE connected" : "○ SSE reconnecting"}
        </span>
      </header>
      {error ? (
        <div className="p-6 text-sm text-red-700">{error}</div>
      ) : (
        <div className="grid min-h-0 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_340px]">
          <section className="flex min-h-[60vh] min-w-0 flex-col">
            <MessageList messages={conversation?.messages ?? []} />
            <MessageComposer onSend={send} />
          </section>
          <TaskPanel tasks={tasks} />
        </div>
      )}
    </div>
  );
}

