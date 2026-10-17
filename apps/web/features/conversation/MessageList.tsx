"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { components } from "@banking/api-client";
import { AssistantTurn } from "./AssistantTurn";
import { buildConversationTurns } from "./timeline";

type Message = components["schemas"]["Message"];
type Task = components["schemas"]["Task"];
type Plan = components["schemas"]["Plan"];
type Workflow = components["schemas"]["Workflow"];
type Report = components["schemas"]["ReportListItem"];

export function MessageList({ messages, tasks, plans, workflows, reports, activityRevision, onRefresh }: {
  messages: Message[];
  tasks: Task[];
  plans: Plan[];
  workflows: Workflow[];
  reports: Report[];
  activityRevision: number;
  onRefresh: () => Promise<void>;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const followLatest = useRef(true);
  const [showLatest, setShowLatest] = useState(false);
  const turns = useMemo(() => buildConversationTurns({ messages, tasks, plans, workflows, reports }), [messages, tasks, plans, workflows, reports]);
  const latestUserMessageId = messages.reduce((latest, message) => message.role === "USER" ? message.message_id : latest, "");

  useEffect(() => {
    followLatest.current = true;
    setShowLatest(false);
    const scroller = scrollRef.current;
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
  }, [latestUserMessageId]);

  useEffect(() => {
    const content = contentRef.current;
    const scroller = scrollRef.current;
    if (!content || !scroller) return;
    const observer = new ResizeObserver(() => {
      if (followLatest.current) scroller.scrollTop = scroller.scrollHeight;
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, []);

  return (
    <div className="relative min-h-0 flex-1">
      <div ref={scrollRef} aria-label="对话消息与回复" className="h-full overflow-y-auto overscroll-contain px-4 py-6 lg:px-6"
        onScroll={() => {
          const scroller = scrollRef.current;
          if (!scroller) return;
          followLatest.current = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 100;
          setShowLatest(!followLatest.current);
        }}
      >
        <div ref={contentRef} className="mx-auto flex min-h-full max-w-[820px] min-w-0 flex-col gap-8">
          {turns.length === 0 && <div className="m-auto max-w-md text-center text-sm text-slate-500">
            试试询问“我有哪些账户？”“分析一下 8 月份消费”或“我有哪些订阅？”。
          </div>}
          {turns.map((turn) => (
            <div key={turn.id} className="min-w-0 space-y-5">
              {turn.user && <article aria-label="用户消息" className="ml-auto w-fit max-w-[85%] rounded-2xl bg-slate-100 px-4 py-3 text-sm text-slate-800">
                <p className="whitespace-pre-wrap break-words">{turn.user.content}</p>
              </article>}
              {(turn.tasks.length > 0 || turn.replies.length > 0 || turn.plans.length > 0 || turn.workflows.length > 0 || turn.reports.length > 0) && (
                <AssistantTurn turn={turn} activityRevision={activityRevision} onRefresh={onRefresh} />
              )}
            </div>
          ))}
        </div>
      </div>
      {showLatest && <button className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full border border-slate-200 bg-white px-4 py-2 text-xs font-medium text-slate-700 shadow-md"
        onClick={() => {
          followLatest.current = true;
          setShowLatest(false);
          scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
        }}
      >↓ 回到最新消息</button>}
    </div>
  );
}
