"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { components } from "@banking/api-client";
import { api } from "@/lib/api/client";
import { StatusBadge } from "@/components/agent-ui/StatusBadge";
import { RiskDetails } from "@/features/workflows/RiskDetails";
import { ReauthenticationForm } from "@/features/workflows/ReauthenticationForm";
import { WorkflowTimeline } from "@/features/workflows/WorkflowTimeline";
import { PayeeSelector } from "./PayeeSelector";
import { queryTime as formatDateTime } from "@/lib/presentation/time";

type Workflow = components["schemas"]["Workflow"];
type TransferState = components["schemas"]["TransferWorkflowState"];

function recurrenceTotal(amount: string, count: number) {
  const [whole, fraction = ""] = amount.split(".");
  const cents = (BigInt(whole) * BigInt(100) + BigInt(fraction.padEnd(2, "0"))) * BigInt(count);
  return `${cents / BigInt(100)}.${String(cents % BigInt(100)).padStart(2, "0")}`;
}

function expiresAt(value: string) {
  return formatDateTime(value);
}

function ReviewDetails({ state, amountDisplay }: { state: TransferState; amountDisplay?: string | null }) {
  const review = state.review_payload;
  if (!review) return null;
  return (
    <dl className="mt-3 grid grid-cols-[88px_1fr] gap-y-2 text-xs">
      <dt className="text-slate-500">转出账户</dt>
      <dd>{review.source_account_display_name} · {review.source_account_masked_number}</dd>
      <dt className="text-slate-500">收款人</dt>
      <dd>{review.payee_display_name} · {review.payee_masked_account}</dd>
      <dt className="text-slate-500">收款银行</dt>
      <dd>{review.payee_bank_name}</dd>
      <dt className="text-slate-500">金额</dt>
      <dd className="font-semibold">{amountDisplay ?? `${review.amount} ${review.currency}`}</dd>
      <dt className="text-slate-500">币种</dt>
      <dd>{review.currency}</dd>
      {review.scheduled_for && <><dt className="text-slate-500">执行时间</dt><dd>{formatDateTime(review.scheduled_for)}</dd><dt className="text-slate-500">最晚执行</dt><dd>{formatDateTime(review.execute_deadline ?? "")}</dd></>}
      {review.recurrence && <><dt className="text-slate-500">周期规则</dt><dd>每月 {review.recurrence.day} 日 {String(review.recurrence.hour).padStart(2, "0")}:{String(review.recurrence.minute).padStart(2, "0")}:{String(review.recurrence.second ?? 0).padStart(2, "0")}，共 {review.recurrence.count} 次</dd><dt className="text-slate-500">授权总额</dt><dd>¥{recurrenceTotal(review.amount, review.recurrence.count)}</dd><dt className="text-slate-500">全部执行日期</dt><dd>{review.recurrence.occurrences.map(value => <p key={value}>{formatDateTime(value)}</p>)}<p className="mt-1 text-slate-500">无此日期的月份跳过；每期超过最晚执行时间即过期，不补扣。</p></dd></>}
      {review.remark && <><dt className="text-slate-500">备注</dt><dd className="break-words">{review.remark}</dd></>}
    </dl>
  );
}

export function TransferWorkflowCard({
  workflow,
  onRefresh,
}: {
  workflow: Workflow;
  onRefresh: () => Promise<void>;
}) {
  const state = (workflow.presentation?.transfer_state ?? workflow.state) as TransferState;
  const required = state.required_input;
  const [busy, setBusy] = useState(false);
  const cancelDialog = useRef<HTMLDialogElement>(null);
  const cancelTitleId = useId();
  const [error, setError] = useState<string | null>(null);
  const [amount, setAmount] = useState("");
  const [recipientQuery, setRecipientQuery] = useState("");
  const [remark, setRemark] = useState(state.draft.remark ?? "");
  const [editing, setEditing] = useState(false);
  const [executionTime, setExecutionTime] = useState(state.draft.recurrence_text ?? "");
  const [schedule, setSchedule] = useState<components["schemas"]["ScheduledTransfer"] | null>(null);
  const scheduleId = state.draft.schedule_id;
  useEffect(() => {
    if (!scheduleId) return;
    let active = true;
    const refresh = () => api.getSchedule(scheduleId).then((value) => {if (active) setSchedule(value);}).catch(() => {});
    void refresh();
    const timer = setInterval(() => void refresh(), 3000);
    return () => { active = false; clearInterval(timer); };
  }, [scheduleId, workflow.version]);
  const appointmentActive = schedule && schedule.status !== "PENDING_AUTHORIZATION";
  const timeEditor = <div className="mt-3"><label className="block text-xs">{state.draft.recurrence_text ? "按月执行规则（请补齐时间和总次数）" : "预约执行时间"}<input value={executionTime} onChange={(event) => setExecutionTime(event.target.value)} placeholder={state.draft.recurrence_text ? "每月1号上午9点，共3次" : "明天早上9点或2026-10-09 09:00"} className="mt-1 w-full rounded border px-2 py-1.5" /></label><button disabled={busy || !executionTime} onClick={() => void act(() => api.setExecutionTime(workflow.workflow_id, executionTime, workflow.version))} className="mt-2 rounded border px-3 py-1.5 text-xs">保存时间并重新核对</button></div>;

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await onRefresh();
    } catch (reason) {
      await onRefresh();
      setError(reason instanceof Error ? reason.message : "操作失败，请刷新后重试");
    } finally {
      setBusy(false);
    }
  }

  const cancel = () => act(async () => {
    if (scheduleId) {const current = await api.getSchedule(scheduleId); setSchedule(await api.scheduleAction(scheduleId, "cancel", current.version));}
    else await api.cancelWorkflow(workflow.workflow_id, workflow.version);
  });
  const stable = ["READY_FOR_REVIEW", "REAUTH_REQUIRED", "READY_FOR_COMMIT"].includes(
    workflow.status,
  );
  const operation = workflow.operation_summary;
  const needsVerification = !appointmentActive && workflow.risk_decision?.required_reauthentication && workflow.reauth_summary?.status !== "VERIFIED";
  const cancellable = [
    "WAITING_FOR_INPUT",
    "READY_FOR_REVIEW",
    "REAUTH_REQUIRED",
    "READY_FOR_COMMIT",
  ].includes(workflow.status);

  const reconcile = () =>
    act(async () => {
      if (!operation) throw new Error("未找到转账操作，请刷新后重试");
      const authoritative = await api.getOperation(operation.operation_id);
      return api.reconcileOperation(authoritative.operation_id, authoritative.version);
    });

  return (
    <section className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-amber-700">
            转账工作流
          </p>
          <p className="mt-1 text-xs text-slate-500">版本 {workflow.version}</p>
        </div>
        {appointmentActive ? <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold">{({SCHEDULED:"已预约，等待执行时间",EXECUTING:"预约执行中",UNKNOWN:"结果确认中",SUCCEEDED:"付款成功",FAILED:"预约执行失败",CANCELLED:"已取消",EXPIRED:"已过期"} as Record<string,string>)[schedule.status] ?? schedule.status}</span> : <StatusBadge status={needsVerification && workflow.status === "READY_FOR_COMMIT" ? "REAUTH_REQUIRED" : workflow.presentation?.business_success === false && workflow.status === "SUCCEEDED" ? "WAITING_EXTERNAL" : workflow.status} />}
      </div>

      {workflow.risk_decision && <RiskDetails risk={workflow.risk_decision} />}
      <WorkflowTimeline workflow={workflow} scheduleStatus={appointmentActive ? schedule.status : undefined} />

      {((workflow.status === "WAITING_FOR_INPUT" && ["RECIPIENT_QUERY", "PAYEE_SELECTION"].includes(required?.type ?? "")) ||
        (workflow.status === "FAILED" && !operation && state.validation?.issues?.some((issue) => issue.code === "PAYEE_NOT_FOUND"))) &&
        <PayeeSelector workflow={workflow} busy={busy} act={act} />}

      {workflow.status === "WAITING_FOR_INPUT" && required?.type === "SOURCE_ACCOUNT_SELECTION" && (
        <div className="mt-3 space-y-2">
          <p className="text-sm font-semibold text-slate-900">请选择付款账户</p>
          {(workflow.presentation?.account_options ?? []).map((option) => (
            <div key={option.account_id} className="rounded-md border border-amber-200 bg-white p-2">
              <p className="text-sm font-semibold text-slate-900">{option.display_name}</p>
              <p className="text-xs text-slate-500">{option.masked_number}</p>
              <p className="mt-1 text-xs text-slate-700">
                可用余额 {option.available_balance_display}
              </p>
              <button
                disabled={busy}
                onClick={() =>
                  void act(() =>
                    api.selectSourceAccount(
                      workflow.workflow_id,
                      option.account_id,
                      workflow.version,
                    ),
                  )
                }
                className="mt-2 rounded bg-slate-900 px-3 py-1 text-xs font-semibold text-white disabled:opacity-50"
              >
                选择
              </button>
            </div>
          ))}
        </div>
      )}

      {workflow.status === "WAITING_FOR_INPUT" && required?.type === "AMOUNT" && (
        <div className="mt-3">
          <label className="text-sm font-semibold text-slate-900" htmlFor={`amount-${workflow.workflow_id}`}>
            转账金额
          </label>
          <div className="mt-2 flex gap-2">
            <input
              id={`amount-${workflow.workflow_id}`}
              inputMode="decimal"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              className="min-w-0 flex-1 rounded border border-amber-200 bg-white px-2 py-1.5 text-sm"
              placeholder="0.00"
            />
            <button
              disabled={busy || !amount}
              onClick={() =>
                void act(() =>
                  api.setTransferAmount(workflow.workflow_id, amount, workflow.version),
                )
              }
              className="rounded bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
            >
              保存
            </button>
          </div>
        </div>
      )}

      {workflow.status === "WAITING_FOR_INPUT" && required?.type === "EXECUTION_TIME" && <><p className="mt-3 text-xs">{required.message}</p>{timeEditor}</>}

      {!appointmentActive && workflow.status === "READY_FOR_REVIEW" && state.review_payload && (
        <div className="mt-3 rounded-md border border-emerald-200 bg-white p-3">
          <p className="text-sm font-semibold text-emerald-800">转账信息已准备完成，尚未提交。</p>
          <ReviewDetails state={state} amountDisplay={workflow.presentation?.amount_display} />
          <p className="mt-3 text-[11px] leading-5 text-slate-500">
            等待确认仅表示当前草稿通过初步校验，不代表已批准，也不保证提交时余额仍然充足。
          </p>
          <button
            disabled={busy}
            onClick={() =>
              void act(() => api.approveTransfer(workflow.workflow_id, workflow.version))
            }
            className="mt-3 rounded bg-emerald-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"
          >
            确认这笔转账
          </button>
        </div>
      )}

      {!appointmentActive && workflow.status === "REAUTH_REQUIRED" && <ReauthenticationForm workflow={workflow} busy={busy} act={act} />}

      {!appointmentActive && workflow.status === "READY_FOR_COMMIT" && state.review_payload && (
        <div className="mt-3 rounded-md border border-indigo-200 bg-white p-3">
          <p className="text-sm font-semibold text-indigo-900">转账信息已确认</p>
          <p className="mt-1 text-sm font-semibold text-emerald-700">
            {needsVerification ? "还需要完成强身份验证" : workflow.risk_decision?.required_reauthentication
              ? "强身份验证已完成" : "用户确认已完成，无需强验证"}
          </p>
          <ReviewDetails state={state} amountDisplay={workflow.presentation?.amount_display} />
          <p className="mt-3 rounded bg-amber-50 p-2 text-xs font-semibold text-amber-800">
            尚未提交转账
          </p>
          <p className="mt-2 text-[11px] leading-5 text-slate-500">
            {needsVerification ? "当前确认来自旧版本，补充强身份验证后才可提交。" : "可以提交表示当前内容已批准并满足当前风险所需的安全控制。提交前会再次评估风险。"}
          </p>
          <p className="mt-3 text-xs font-semibold text-red-700">
            {needsVerification ? "旧版本确认需要补充强验证后才能转账" : scheduleId ? state.draft.recurrence ? "创建有限次按月模拟转账，到各期日期自动执行" : "创建单次模拟转账预约，到时自动执行" : "这一步将提交模拟资金转账"}
          </p>
          <button
            disabled={busy}
            onClick={() =>
              void act(async () => {
                if (scheduleId) setSchedule(await api.scheduleAction(scheduleId, "authorize", workflow.version));
                else await api.commitTransfer(workflow.workflow_id, workflow.version);
              })
            }
            className="mt-2 rounded bg-red-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"
          >
            {needsVerification ? "去强验证" : scheduleId ? state.draft.recurrence ? "授权并创建周期转账" : "授权并创建预约" : "提交转账"}
          </button>
        </div>
      )}

      {workflow.status === "COMMITTING" && operation && (
        <div className="mt-3 rounded-md border border-blue-200 bg-white p-3">
          {operation.status === "UNKNOWN" ? (
            <>
              <p className="text-sm font-semibold text-blue-900">转账状态确认中</p>
              <p className="mt-2 text-xs leading-5 text-slate-700">
                银行可能已经收到这笔请求，请勿重复提交。
              </p>
            </>
          ) : (
            <>
              <p className="text-sm font-semibold text-blue-900">正在提交转账</p>
              <p className="mt-2 text-xs text-slate-700">请勿重复操作</p>
            </>
          )}
          <ReviewDetails state={state} amountDisplay={workflow.presentation?.amount_display} />
          <button
            disabled={busy}
            onClick={() => void reconcile()}
            className="mt-3 rounded border border-blue-300 px-3 py-2 text-xs font-semibold text-blue-800 disabled:opacity-50"
          >
            检查状态
          </button>
        </div>
      )}

      {workflow.status === "SUCCEEDED" && operation?.status === "SUCCEEDED" && (
        <div className="mt-3 rounded-md border border-emerald-200 bg-white p-3">
          <p className="text-sm font-semibold text-emerald-800">转账成功</p>
          <ReviewDetails state={state} amountDisplay={workflow.presentation?.amount_display} />
          {operation.provider_reference && (
            <p className="mt-3 text-xs text-slate-600">
              银行参考号：{operation.provider_reference}
            </p>
          )}
          {operation.completed_at && (
            <p className="mt-1 text-xs text-slate-500">
              完成时间：{expiresAt(operation.completed_at)}
            </p>
          )}
        </div>
      )}

      {state.draft.schedule_requested && <p className="mt-3 text-xs text-amber-900">仅支持 Mock 预约，到时自动执行模拟转账；不冻结余额，每期重新检查余额与安全状态。周期必须限定次数，创建成功不代表付款成功。</p>}
      {appointmentActive && <div className="mt-3 rounded border bg-white p-3"><p className="font-semibold">预约状态：{({SCHEDULED:"已预约", EXECUTING:"执行中", UNKNOWN:"结果未知", SUCCEEDED:"付款成功", FAILED:"失败，需要检查或重新授权", CANCELLED:"已取消", EXPIRED:"已过期"} as Record<string,string>)[schedule.status] ?? schedule.status}</p><p className="my-2 text-sm text-slate-600">{schedule.status === "SCHEDULED" ? "预约已创建，无需再次提交。到达执行时间后系统会自动执行模拟转账，执行前重新检查余额与安全状态。" : "预约创建与实际付款分别记录，请以最终付款结果为准。"}</p><ReviewDetails state={state} />{schedule.error_code && <p className="text-xs text-red-700">{schedule.error_code}</p>}{schedule.operation_id && <button className="mt-2 text-xs underline" disabled={busy} onClick={() => void act(async () => {const op = await api.getOperation(schedule.operation_id!); await api.reconcileOperation(op.operation_id, op.version); setSchedule(await api.getSchedule(scheduleId!));})}>查询原操作</button>}{schedule.series_id && <p className="mt-2 text-xs">按月周期第 {schedule.occurrence_index} 期 · {schedule.series_revoked ? "后续授权已撤销" : "周期授权有效"}。取消本期不影响其他期次；撤销后续期次请进入列表。</p>}<a href="/scheduled-transfers" className="ml-3 text-xs underline">预约与周期列表</a></div>}
      {stable && !state.draft.aa_share_id && (!appointmentActive || schedule?.status === "SCHEDULED") && !schedule?.series_id && (
        <div className="mt-3 border-t border-amber-200 pt-3">
          <button
            className="text-xs font-semibold text-slate-600 underline"
            onClick={() => setEditing((value) => !value)}
          >
            {editing ? "收起修改" : "修改转账草稿"}
          </button>
          {editing && (
            <div className="mt-3 space-y-3 rounded-md bg-white p-3">
              <p className="text-[11px] text-amber-800">任何修改都会使现有确认和身份验证失效。</p>
              {state.draft.schedule_requested && timeEditor}
              <label className="block text-xs">转账备注（选填）<input value={remark} maxLength={100} onChange={(event) => setRemark(event.target.value)} className="mt-1 w-full rounded border px-2 py-1.5" /></label>
              <button disabled={busy} onClick={() => void act(() => api.setTransferRemark(workflow.workflow_id, remark, workflow.version))} className="rounded border px-3 py-1.5 text-xs">保存备注并重新核对</button>
              <div className="flex gap-2">
                <input
                  value={recipientQuery}
                  onChange={(event) => setRecipientQuery(event.target.value)}
                  placeholder={state.draft.recipient_query ?? "新收款人"}
                  className="min-w-0 flex-1 rounded border px-2 py-1.5 text-xs"
                />
                <button
                  disabled={busy || !recipientQuery.trim()}
                  onClick={() =>
                    void act(() =>
                      api.setRecipientQuery(
                        workflow.workflow_id,
                        recipientQuery.trim(),
                        workflow.version,
                      ),
                    )
                  }
                  className="rounded border px-2 py-1 text-xs font-semibold disabled:opacity-50"
                >
                  修改收款人
                </button>
              </div>
              <div className="flex gap-2">
                <input
                  inputMode="decimal"
                  value={amount}
                  onChange={(event) => setAmount(event.target.value)}
                  placeholder={state.draft.amount ?? "新金额"}
                  className="min-w-0 flex-1 rounded border px-2 py-1.5 text-xs"
                />
                <button
                  disabled={busy || !amount}
                  onClick={() =>
                    void act(() =>
                      api.setTransferAmount(workflow.workflow_id, amount, workflow.version),
                    )
                  }
                  className="rounded border px-2 py-1 text-xs font-semibold disabled:opacity-50"
                >
                  修改金额
                </button>
              </div>
              <PayeeSelector workflow={workflow} busy={busy} act={act} />
              <div>
                <p className="text-xs font-semibold text-slate-700">更换付款账户</p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {(workflow.presentation?.account_options ?? []).map((option) => (
                    <button
                      key={option.account_id}
                      disabled={busy || state.draft.source_account_id === option.account_id}
                      onClick={() =>
                        void act(() =>
                          api.selectSourceAccount(
                            workflow.workflow_id,
                            option.account_id,
                            workflow.version,
                          ),
                        )
                      }
                      className="rounded border px-2 py-1 text-[11px] disabled:opacity-40"
                    >
                      {option.display_name} · {option.masked_number}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {workflow.status === "FAILED" && (
        <div className="mt-3 rounded-md bg-red-50 p-2 text-xs text-red-700">
          {operation?.status === "FAILED" && (
            <>
              <p className="font-semibold">转账未成功</p>
              <p className="mt-1">{operation.error_code ?? "银行已明确确认本次转账未成功"}</p>
              <p className="mt-1">如需再次转账，请重新发起。</p>
            </>
          )}
          {state.validation?.issues?.map((issue) => (
            <p key={issue.code}>{issue.code}：{issue.message}</p>
          ))}
        </div>
      )}

      <dialog ref={cancelDialog} aria-labelledby={cancelTitleId} className="w-[calc(100%-40px)] max-w-md rounded-xl border-0 bg-white p-6 text-slate-900 shadow-xl backdrop:bg-slate-950/50">
        <h2 id={cancelTitleId} className="text-lg font-semibold">确认取消转账？</h2>
        <p className="mt-3 text-sm text-slate-600">{appointmentActive ? "取消后，这笔转账将不再按预约时间执行。" : "取消后，如需转账，请重新发起。"}</p>
        <div className="mt-5 flex justify-end gap-3">
          <button autoFocus type="button" onClick={() => cancelDialog.current?.close()} className="rounded-lg border px-4 py-2 text-sm">暂不取消</button>
          <button type="button" disabled={busy} onClick={() => { cancelDialog.current?.close(); void cancel(); }} className="rounded-lg bg-red-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">确认取消转账</button>
        </div>
      </dialog>
      {error && <p className="mt-2 text-xs text-red-700">{error}</p>}
      {cancellable && !state.draft.aa_share_id && (!appointmentActive || schedule?.status === "SCHEDULED") && !schedule?.series_id && (
        <button
          disabled={busy}
          onClick={() => cancelDialog.current?.showModal()}
          className="mt-3 text-xs font-semibold text-slate-500 underline disabled:opacity-50"
        >
          取消转账
        </button>
      )}
    </section>
  );
}
