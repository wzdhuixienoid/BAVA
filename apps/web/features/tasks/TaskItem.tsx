import type { components } from "@banking/api-client";
import { TaskStatus } from "@/components/agent-ui/TaskStatus";

type Task = components["schemas"]["Task"];

export function TaskItem({ task }: { task: Task }) {
  return (
    <article className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex items-start justify-between gap-3">
        <p className="break-all text-xs font-semibold text-slate-800">{task.task_type}</p>
        <TaskStatus status={task.status} />
      </div>
      <p className="mt-2 break-all font-mono text-[10px] text-slate-500">{task.task_id}</p>
      <p className="mt-1 text-[10px] text-slate-400">server version {task.version}</p>
    </article>
  );
}

