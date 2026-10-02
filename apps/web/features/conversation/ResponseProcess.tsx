"use client";

import { useEffect, useState } from "react";
import { TaskActivity, useTaskActivity } from "@/features/tasks/TaskActivity";
import { responseState, type ConversationTurn } from "./timeline";

export function ResponseProcess({ turn, activityRevision }: {
  turn: ConversationTurn;
  activityRevision: number;
  onRefresh: () => Promise<void>;
}) {
  const state = responseState(turn);
  const [expanded, setExpanded] = useState(state.active);
  useEffect(() => { setExpanded(state.active); }, [state.active]);
  const revision = `${activityRevision}:${turn.tasks.map((task) => task.version)}:${turn.plans.map((plan) => plan.version)}:${turn.workflows.map((workflow) => workflow.version)}`;
  const activity = useTaskActivity(turn.tasks.map((task) => task.task_id), revision, state.active || expanded);
  const latest = activity.entries.at(-1)?.text;
  const progress = state.label === "正在思考与处理"
    ? latest ?? turn.tasks.at(-1)?.progress_message ?? state.label
    : state.label;

  return (
    <details open={expanded} onToggle={(event) => setExpanded(event.currentTarget.open)} className="group mb-5 text-slate-500">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-xs hover:text-slate-800 [&::-webkit-details-marker]:hidden">
        {state.active ? <span className="h-3 w-3 shrink-0 animate-spin rounded-full border-2 border-slate-200 border-t-cyan-600 motion-reduce:animate-none" /> : <span className={state.failed ? "text-red-500" : "text-slate-400"}>{state.failed ? "!" : state.label === "已完成处理" ? "✓" : "○"}</span>}
        <span aria-live="polite" className="min-w-0 break-words">{progress}</span>
        <span className="ml-1 shrink-0 text-[10px] text-slate-400">{expanded ? "收起过程" : "查看过程"} <span className="inline-block transition-transform group-open:rotate-90">›</span></span>
      </summary>
      <div className="mt-4 space-y-4">
        <TaskActivity {...activity} />
      </div>
    </details>
  );
}
