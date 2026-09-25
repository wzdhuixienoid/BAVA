import type { components } from "@banking/api-client";
import { TaskStatus } from "@/components/agent-ui/TaskStatus";
import { ReportCard } from "@/features/reports/ReportCard";
import { TaskProgress } from "./TaskProgress";
import { TransferWorkflowCard } from "@/features/workflows/transfer/TransferWorkflowCard";

type Task = components["schemas"]["Task"];
type ReportListItem = components["schemas"]["ReportListItem"];
type Workflow = components["schemas"]["Workflow"];

const taskTypeLabels: Record<string, string> = {
  BANKING_REQUEST: "银行服务请求",
  MINIMAL_AGENT_RUN: "银行账户请求",
};

export function TaskItem({
  task,
  report,
  workflow,
  onRefresh,
}: {
  task: Task;
  report?: ReportListItem;
  workflow?: Workflow;
  onRefresh: () => Promise<void>;
}) {
  return (
    <article className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold text-slate-800">
            {taskTypeLabels[task.task_type] ?? "银行服务任务"}
          </p>
        </div>
        <TaskStatus status={task.status} />
      </div>
      <TaskProgress
        message={
          task.status === "INTERRUPTED"
            ? "任务因运行服务中断而暂停，请稍后重试。"
            : task.progress_message
        }
      />
      <p className="mt-2 break-all font-mono text-[10px] text-slate-500">
        任务 ID：{task.task_id}
      </p>
      <p className="mt-1 text-[10px] text-slate-400">服务端版本 {task.version}</p>
      <ReportCard task={task} report={report} />
      {workflow?.workflow_type === "TRANSFER" && (
        <TransferWorkflowCard workflow={workflow} onRefresh={onRefresh} />
      )}
    </article>
  );
}
