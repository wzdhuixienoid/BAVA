import type { components } from "@banking/api-client";

type TaskStatusValue = components["schemas"]["TaskStatus"];

const colors: Record<TaskStatusValue, string> = {
  PENDING: "bg-amber-100 text-amber-800",
  RUNNING: "bg-blue-100 text-blue-800",
  WAITING_USER: "bg-purple-100 text-purple-800",
  WAITING_EXTERNAL: "bg-purple-100 text-purple-800",
  COMPLETED: "bg-emerald-100 text-emerald-800",
  FAILED: "bg-red-100 text-red-800",
  CANCELLED: "bg-slate-200 text-slate-700",
  SKIPPED: "bg-slate-200 text-slate-700",
};

export function TaskStatus({ status }: { status: TaskStatusValue }) {
  return <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${colors[status]}`}>{status}</span>;
}

