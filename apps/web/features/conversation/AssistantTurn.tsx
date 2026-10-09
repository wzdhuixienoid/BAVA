import type { components } from "@banking/api-client";
import { subscriptionReport } from "@/features/subscriptions/answer";
import { AARequestCard } from "@/features/aa/AARequestCard";
import { PlanCard } from "@/features/plans/PlanCard";
import { AccountAnswer } from "@/features/accounts/AccountAnswer";
import { AuditPanel } from "@/features/audit/AuditPanel";
import { accountResults } from "@/features/accounts/presentation";
import { ReportCard } from "@/features/reports/ReportCard";
import { WorkflowReceipt } from "@/features/results/WorkflowReceipt";
import { TransferWorkflowCard } from "@/features/workflows/transfer/TransferWorkflowCard";
import { SubscriptionCancellationCard } from "@/features/workflows/subscriptions/SubscriptionCancellationCard";
import { MarkdownMessage } from "./MarkdownMessage";
import { localizeFinancialAnswer, requestsAnomalyAnalysis } from "./financialAnswer";
import { ResponseProcess } from "./ResponseProcess";
import { isConfirmedWorkflow, resultElementId, type ConversationTurn } from "./timeline";


function ReadPreview({ output }: { output: Record<string, unknown> }) {
  const accounts = output.account_results as Array<{
    display_name?: string; balance?: string; currency?: string;
    accounts?: Array<{ display_name: string; masked_number?: string }>;
  }> | undefined;
  const legacyAccounts = accounts?.filter((account) => !("kind" in account));
  const analysis = output.analysis_snapshot as { spending_summary?: { period: string; total_spending: string; total_income: string; currency: string } } | undefined;
  const summary = analysis?.spending_summary;
  if (!legacyAccounts?.length && !summary) return null;
  return (
    <div className="rounded-lg bg-slate-50 p-3 text-sm leading-relaxed">
      {legacyAccounts?.map((account, index) => <div key={index}>
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
  const unrequestedAnomalies = Boolean(turn.user && !requestsAnomalyAnalysis(turn.user.content)
    && outputs.some((output) => output.transaction_anomaly_snapshot));
  const anomalyAnswer = unrequestedAnomalies ? null : outputs.find((output) =>
    typeof output.transaction_anomaly_answer === "string")?.transaction_anomaly_answer as string | undefined;
  const anomalySnapshot = outputs.find((output) => output.transaction_anomaly_snapshot)?.transaction_anomaly_snapshot as {
    analysis_period_started_at: string; analysis_period_ended_at: string;
  } | undefined;
  const historicalYearMismatch = Boolean(anomalySnapshot && turn.user && /(?:近|最近|过去)(?:一|1)年/.test(turn.user.content)
    && new Date(anomalySnapshot.analysis_period_ended_at).getTime() - new Date(anomalySnapshot.analysis_period_started_at).getTime() < 364 * 86400000);
  const highlight = (id: string) => highlightedResult === id ? "rounded-xl ring-2 ring-cyan-500 ring-offset-4" : "";
  const hasAnswer = turn.replies.some((message) => message.role === "ASSISTANT");
  const accounts = accountResults(outputs);
  const isFinancialAnalysis = outputs.some((output) => output.analysis_snapshot || output.financial_display);
  const needsHistoricalCorrection = unrequestedAnomalies;
  const accountOnlyAnswer = accounts.length > 0 && !isFinancialAnalysis && !anomalyAnswer
    && !outputs.some((output) => output.payee_results)
    && !turn.plans.length && !turn.workflows.length && !turn.reports.length;
  const replies = needsHistoricalCorrection || accountOnlyAnswer
    ? turn.replies.filter((message) => message.role === "SYSTEM_NOTICE") : turn.replies;
  const subscriptionSnapshot = outputs.find(output => output.subscription_analysis_snapshot)?.subscription_analysis_snapshot as components["schemas"]["SubscriptionAnalysisSnapshot"] | undefined;
  const replyContent = (content: string) => isFinancialAnalysis ? localizeFinancialAnswer(content, outputs) : content;

  return (
    <article aria-label="助理回复" className="min-w-0 py-2 text-sm text-slate-800">
      <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-slate-700">
        <span aria-hidden="true" className="grid h-6 w-6 place-items-center rounded-full bg-slate-900 text-[10px] text-white">B</span>
        银行助理
      </div>
      <div className="min-w-0 pl-0 sm:pl-8">
        {!subscriptionSnapshot && (turn.tasks.length > 0 || turn.plans.length > 0 || turn.workflows.length > 0) && (
          <ResponseProcess turn={turn} activityRevision={activityRevision} onRefresh={onRefresh} />
        )}
        <div className="space-y-4">
          {!subscriptionSnapshot && turn.tasks.map((task) => <AuditPanel key={task.task_id} taskId={task.task_id} revision={activityRevision} />)}
          {turn.tasks.map((task) => typeof task.error?.message === "string" ? <p key={task.task_id} role="alert" className="text-red-700">{task.error.code === "REPORT_NARRATIVE_VALIDATION_FAILED" ? "报告说明未通过安全校验，请重新生成。" : task.error.message}</p> : null)}
          {!hasAnswer && outputs.map((output, index) => <ReadPreview key={index} output={output} />)}
          {turn.tasks.filter(task => typeof task.output?.aa_request_id === "string").map(task => <AARequestCard key={task.task_id} requestId={String(task.output!.aa_request_id)} />)}
          {turn.plans.map((plan) => <PlanCard key={plan.plan_id} plan={plan} workflows={[]} onRefresh={onRefresh} />)}
          {accounts.length > 0 && <AccountAnswer results={accounts} />}
          {needsHistoricalCorrection && <p className="text-slate-600">这条历史回复误用了异常交易分析，未按你指定的消费范围执行。现在可按最近任意天数分析消费。</p>}

          {turn.reports.map((report) => {
            const id = `report-${report.report_id}`;
            return <div key={id} id={resultElementId(id)} tabIndex={-1} className={highlight(id)}><ReportCard report={report} /></div>;
          })}
          {turn.tasks.filter((task) => typeof task.output?.report_id === "string" && task.output?.report_deleted !== true && !turn.reports.some((report) => report.report_id === task.output?.report_id)).map((task) => {
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
          <div className="space-y-3">
          {historicalYearMismatch && !unrequestedAnomalies && <p className="text-slate-600">这条历史结果只覆盖下面标明的区间，未覆盖你要求的近一年。现在已支持近一年分析，需重新查询才能取得完整区间的结果。</p>}
          {subscriptionSnapshot ? <MarkdownMessage content={subscriptionReport(subscriptionSnapshot)} /> : anomalyAnswer ? <MarkdownMessage content={anomalyAnswer} /> : replies.map((message) => <div key={message.message_id}>
            {message.role === "SYSTEM_NOTICE" && <p className="mb-1 text-xs text-slate-400">系统通知</p>}
            <MarkdownMessage content={replyContent(message.content)} />
          </div>)}
          </div>
        </div>
      </div>
    </article>
  );
}
