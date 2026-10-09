import type { components } from "@banking/api-client";

type Message = components["schemas"]["Message"];
type Task = components["schemas"]["Task"];
type Plan = components["schemas"]["Plan"];
type Workflow = components["schemas"]["Workflow"];
type Report = components["schemas"]["ReportListItem"];

export type ConversationTurn = {
  id: string;
  user?: Message;
  replies: Message[];
  tasks: Task[];
  plans: Plan[];
  workflows: Workflow[];
  reports: Report[];
};

function emptyTurn(id: string, user?: Message): ConversationTurn {
  return { id, user, replies: [], tasks: [], plans: [], workflows: [], reports: [] };
}

export function buildConversationTurns({ messages, tasks, plans, workflows, reports }: {
  messages: Message[]; tasks: Task[]; plans: Plan[]; workflows: Workflow[]; reports: Report[];
}): ConversationTurn[] {
  // Future derived occurrences are already listed in the original cycle review.
  // Surface each occurrence in the conversation once it starts or has a result.
  const futureOccurrences = new Set(tasks.filter(task => task.task_type === "recurring_transfer_occurrence" && workflows.some(workflow => workflow.source_task_id === task.task_id && workflow.status === "READY_FOR_COMMIT" && !workflow.operation_summary)).map(task => task.task_id));
  tasks = tasks.filter(task => !futureOccurrences.has(task.task_id));
  workflows = workflows.filter(workflow => !futureOccurrences.has(workflow.source_task_id));
  const turns: ConversationTurn[] = [];
  const userTurns = new Map<string, ConversationTurn>();
  const fallbackOwners = new Map<string, ConversationTurn>();
  let current: ConversationTurn | undefined;
  for (const message of messages) {
    if (message.role === "USER") {
      current = emptyTurn(`message-${message.message_id}`, message);
      userTurns.set(message.message_id, current);
      turns.push(current);
    } else {
      if (!current) {
        current = emptyTurn(`message-${message.message_id}`);
        turns.push(current);
      }
      fallbackOwners.set(message.message_id, current);
    }
  }

  const taskTurns = new Map<string, ConversationTurn>();
  const answerOwners = new Map<string, ConversationTurn>();
  function ensureTaskTurn(taskId: string): ConversationTurn {
    let turn = taskTurns.get(taskId);
    if (!turn) {
      turn = emptyTurn(`task-${taskId}`);
      taskTurns.set(taskId, turn);
      turns.push(turn);
    }
    return turn;
  }
  for (const task of tasks) {
    const sourceId = task.input.message_id;
    const answerId = task.output?.assistant_message_id;
    const turn = (typeof sourceId === "string" ? userTurns.get(sourceId) : undefined)
      ?? (typeof answerId === "string" ? fallbackOwners.get(answerId) : undefined)
      ?? ensureTaskTurn(task.task_id);
    taskTurns.set(task.task_id, turn);
    turn.tasks.push(task);
    if (typeof answerId === "string") answerOwners.set(answerId, turn);
  }
  for (const message of messages) {
    if (message.role === "USER") continue;
    const turn = answerOwners.get(message.message_id) ?? fallbackOwners.get(message.message_id);
    turn?.replies.push(message);
  }
  for (const plan of plans) ensureTaskTurn(plan.source_task_id).plans.push(plan);
  for (const workflow of workflows) ensureTaskTurn(workflow.source_task_id).workflows.push(workflow);
  for (const report of reports) ensureTaskTurn(report.source_task_id).reports.push(report);
  return turns.filter((turn) => turn.user || turn.replies.length || turn.tasks.length || turn.plans.length || turn.workflows.length || turn.reports.length);
}

export function isConfirmedWorkflow(workflow: Workflow): boolean {
  if (workflow.presentation) return workflow.presentation.business_success;
  return workflow.status === "SUCCEEDED" && workflow.operation_summary?.status === "SUCCEEDED";
}

export function responseState(turn: ConversationTurn): { active: boolean; label: string; failed: boolean } {
  if (turn.plans.some((plan) => plan.status === "FAILED") || turn.workflows.some((workflow) => workflow.status === "FAILED") || turn.tasks.some((task) => task.status === "FAILED")) {
    return { active: false, label: "处理未完成", failed: true };
  }
  if (turn.workflows.some((workflow) => workflow.status === "COMMITTING" || (workflow.status === "SUCCEEDED" && !isConfirmedWorkflow(workflow))) || turn.plans.some((plan) => plan.status === "WAITING_EXTERNAL")) {
    return { active: true, label: "正在等待银行确认结果", failed: false };
  }
  if (turn.plans.some((plan) => plan.status === "PAUSED")) return { active: false, label: "已暂停，等待你继续", failed: false };
  if (turn.workflows.some((workflow) => ["WAITING_FOR_INPUT", "READY_FOR_REVIEW", "REAUTH_REQUIRED", "READY_FOR_COMMIT"].includes(workflow.status)) || turn.plans.some((plan) => plan.status === "WAITING_USER") || turn.tasks.some((task) => task.status === "WAITING_USER")) {
    return { active: false, label: "等待你的操作", failed: false };
  }
  // A workflow draft can outlive its completed background task.
  if (turn.workflows.some((workflow) => ["DRAFT", "VALIDATING"].includes(workflow.status)) || turn.plans.some((plan) => plan.status === "RUNNING") || turn.tasks.some((task) => ["PENDING", "RUNNING"].includes(task.status))) {
    return { active: true, label: "正在思考与处理", failed: false };
  }
  if (turn.tasks.some((task) => task.status === "WAITING_EXTERNAL")) return { active: true, label: "正在等待外部结果", failed: false };
  if (turn.tasks.some((task) => task.status === "INTERRUPTED")) return { active: false, label: "处理已中断，等待恢复", failed: false };
  if (turn.plans.some((plan) => plan.status === "CANCELLED") || turn.workflows.some((workflow) => workflow.status === "CANCELLED") || turn.tasks.some((task) => task.status === "CANCELLED")) {
    return { active: false, label: "已取消处理", failed: false };
  }
  return { active: false, label: "已完成处理", failed: false };
}

export function resultElementId(resultId: string): string {
  return `conversation-result-${resultId}`;
}
