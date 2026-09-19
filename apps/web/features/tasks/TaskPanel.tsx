import type { components } from "@banking/api-client";
import { TaskItem } from "./TaskItem";

type Task = components["schemas"]["Task"];

export function TaskPanel({ tasks }: { tasks: Task[] }) {
  return (
    <aside className="border-t border-slate-200 bg-slate-50 p-4 lg:border-l lg:border-t-0">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-600">Tasks</h2>
      <div className="space-y-2">
        {tasks.length === 0 && <p className="text-sm text-slate-400">No tasks yet.</p>}
        {tasks.map((task) => <TaskItem key={task.task_id} task={task} />)}
      </div>
    </aside>
  );
}

