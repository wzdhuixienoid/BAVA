import type { components } from "@banking/api-client";
import { ReportCard } from "@/features/reports/ReportCard";
import { WorkflowReceipt } from "@/features/results/WorkflowReceipt";
import { TransferWorkflowCard } from "@/features/workflows/transfer/TransferWorkflowCard";
import { SubscriptionCancellationCard } from "@/features/workflows/subscriptions/SubscriptionCancellationCard";
import { SubscriptionSummaryCard } from "@/features/subscriptions/SubscriptionSummaryCard";
import { TransactionAnomalyCard, type TransactionAnomalySnapshot } from "@/features/anomalies/TransactionAnomalyCard";
import { MarkdownMessage } from "./MarkdownMessage";
import { ResponseProcess } from "./ResponseProcess";
import { isConfirmedWorkflow, resultElementId, type ConversationTurn } from "./timeline";

type SubscriptionSnapshot = components["schemas"]["SubscriptionAnalysisSnapshot"];

function ReadPreview({ output }: { output: Record<string, unknown> }) {
  const accounts = output.account_results as Array<{
    display_name?: string; balance?: string; currency?: string;
    accounts?: Array<{ display_name: string; masked_number?: string }>;
  }> | undefined;
  const analysis = output.analysis_snapshot as { spending_summary?: { period: string; total_spending: string; total_income: string; currency: string } } | undefined;
  const summary = analysis?.spending_summary;
  if (!accounts && !summary) return null;
  return (
    <div className="rounded-lg bg-slate-50 p-3 text-sm leading-relaxed">
      {accounts?.map((account, index) => <div key={index}>
        {account.balance && <p>{account.display_name ?? "账户"}：余额 <strong>{account.balance} {account.currency}</strong></p>}
        {account.accounts?.map((item, position) => <p key={position}>{item.display_name} {item.masked_number}</p>)}
      </div>)}
      {summary && <p>{summary.period}：支出 <strong>{summary.total_spending} {summary.currency}</strong>，收入 {summary.total_income} {summary.currency}</p>}
    </div>
  );
}

export function AssistantTurn({ turn, activityRevision, highlightedResult, onRefresh }: {
  turn: ConversationTurn;
  activityRevision: number;
  highlightedResult: string | null;
  onRefresh: () => Promise<void>;
}) {
  const outputs = [
    ...turn.tasks.map((task) => task.output),
    ...turn.plans.flatMap((plan) => plan.steps.filter((step) => step.status === "COMPLETED").map((step) => step.result_summary)),
  ].filter((output): output is Record<string, unknown> => Boolean(output));
  const subscriptions = [...new Map(outputs.filter((output) => output.subscription_analysis_snapshot)
    .map((output) => [JSON.stringify(output.subscription_analysis_snapshot), output.subscription_analysis_snapshot as SubscriptionSnapshot])).values()];
  const anomalies = [...new Map(outputs.filter((output) => output.transaction_anomaly_snapshot)
    .map((output) => [JSON.stringify(output.transaction_anomaly_snapshot), output.transaction_anomaly_snapshot as TransactionAnomalySnapshot])).values()];
  const highlight = (id: string) => highlightedResult === id ? "rounded-xl ring-2 ring-cyan-500 ring-offset-4" : "";
  const hasAnswer = turn.replies.some((message) => message.role === "ASSISTANT");

  return (
    <article aria-label="助理回复" className="min-w-0 py-2 text-sm text-slate-800">
      <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-slate-700">
        <span aria-hidden="true" className="grid h-6 w-6 place-items-center rounded-full bg-slate-900 text-[10px] text-white">B</span>
        银行助理
      </div>
      <div className="min-w-0 pl-0 sm:pl-8">
        {(turn.tasks.length > 0 || turn.plans.length > 0 || turn.workflows.length > 0) && (
          <ResponseProcess turn={turn} activityRevision={activityRevision} onRefresh={onRefresh} />
        )}
        <div className="space-y-4">
          {turn.replies.map((message) => <div key={message.message_id}>
            {message.role === "SYSTEM_NOTICE" && <p className="mb-1 text-xs text-slate-400">系统通知</p>}
            <MarkdownMessage content={message.content} />
          </div>)}
          {turn.tasks.map((task) => typeof task.error?.message === "string" ? <p key={task.task_id} role="alert" className="text-red-700">{task.error.message}</p> : null)}
          {!hasAnswer && outputs.map((output, index) => <ReadPreview key={index} output={output} />)}
          {subscriptions.map((snapshot, index) => <SubscriptionSummaryCard key={index} snapshot={snapshot} />)}
          {anomalies.map((snapshot, index) => <TransactionAnomalyCard key={index} snapshot={snapshot} />)}
          {turn.reports.map((report) => {
            const id = `report-${report.report_id}`;
            return <div key={id} id={resultElementId(id)} tabIndex={-1} className={highlight(id)}><ReportCard report={report} /></div>;
          })}
          {turn.tasks.filter((task) => typeof task.output?.report_id === "string" && !turn.reports.some((report) => report.report_id === task.output?.report_id)).map((task) => {
            const id = `report-${task.output!.report_id}`;
            return <div key={id} id={resultElementId(id)} tabIndex={-1} className={highlight(id)}><ReportCard task={task} /></div>;
          })}
          {turn.workflows.map((workflow) => {
            const id = `workflow-${workflow.workflow_id}`;
            return <div key={id} id={resultElementId(id)} tabIndex={-1} className={highlight(id)}>
              {isConfirmedWorkflow(workflow) ? <WorkflowReceipt workflow={workflow} />
                : workflow.workflow_type === "TRANSFER" ? <TransferWorkflowCard workflow={workflow} onRefresh={onRefresh} />
                : <SubscriptionCancellationCard workflow={workflow} onRefresh={onRefresh} />}
            </div>;
          })}
        </div>
      </div>
    </article>
  );
}
