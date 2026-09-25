import type { components } from "@banking/api-client";
import { TaskItem } from "./TaskItem";

type Task = components["schemas"]["Task"];
type ReportListItem = components["schemas"]["ReportListItem"];
type Workflow = components["schemas"]["Workflow"];

export function TaskPanel({
  tasks,
  reports,
  workflows,
  onRefresh,
}: {
  tasks: Task[];
  reports: ReportListItem[];
  workflows: Workflow[];
  onRefresh: () => Promise<void>;
}) {
  const reportsByTask = new Map(reports.map((report) => [report.source_task_id, report]));
  const workflowsById = new Map(
    workflows.map((workflow) => [workflow.workflow_id, workflow]),
  );

  return (
    <aside className="border-t border-slate-200 bg-slate-50 p-4 lg:border-l lg:border-t-0">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-600">任务</h2>
      <div className="space-y-2">
        {tasks.length === 0 && <p className="text-sm text-slate-400">暂无任务。</p>}
        {tasks.map((task) => (
          <TaskItem
            key={task.task_id}
            task={task}
            report={reportsByTask.get(task.task_id)}
            workflow={
              typeof task.output?.workflow_id === "string"
                ? workflowsById.get(task.output.workflow_id)
                : undefined
            }
            onRefresh={onRefresh}
          />
        ))}
      </div>
    </aside>
  );
}
