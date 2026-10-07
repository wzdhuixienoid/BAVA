"use client";

import { useState } from "react";
import type { components } from "@banking/api-client";
import { api } from "@/lib/api/client";
import { StatusBadge } from "@/components/agent-ui/StatusBadge";
import { RiskDetails } from "@/features/workflows/RiskDetails";
import { ReauthenticationForm } from "@/features/workflows/ReauthenticationForm";
import { WorkflowTimeline } from "@/features/workflows/WorkflowTimeline";
import { PayeeSelector } from "./PayeeSelector";

type Workflow = components["schemas"]["Workflow"];
type TransferState = components["schemas"]["TransferWorkflowState"];

function expiresAt(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "medium" }).format(new Date(value));
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
  const [error, setError] = useState<string | null>(null);
  const [amount, setAmount] = useState("");
  const [recipientQuery, setRecipientQuery] = useState("");
  const [editing, setEditing] = useState(false);

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

  const cancel = () => act(() => api.cancelWorkflow(workflow.workflow_id, workflow.version));
  const stable = ["READY_FOR_REVIEW", "REAUTH_REQUIRED", "READY_FOR_COMMIT"].includes(
    workflow.status,
  );
  const operation = workflow.operation_summary;
  const needsVerification = workflow.risk_decision?.required_reauthentication && workflow.reauth_summary?.status !== "VERIFIED";
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
        <StatusBadge status={needsVerification && workflow.status === "READY_FOR_COMMIT" ? "REAUTH_REQUIRED" : workflow.presentation?.business_success === false && workflow.status === "SUCCEEDED" ? "WAITING_EXTERNAL" : workflow.status} />
      </div>

      {workflow.risk_decision && <RiskDetails risk={workflow.risk_decision} />}
      <WorkflowTimeline workflow={workflow} />

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

      {workflow.status === "READY_FOR_REVIEW" && state.review_payload && (
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

      {workflow.status === "REAUTH_REQUIRED" && <ReauthenticationForm workflow={workflow} busy={busy} act={act} />}

      {workflow.status === "READY_FOR_COMMIT" && state.review_payload && (
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
            {needsVerification ? "旧版本确认需要补充强验证后才能转账" : "这一步将真正提交资金转账"}
          </p>
          <button
            disabled={busy}
            onClick={() =>
              void act(() => api.commitTransfer(workflow.workflow_id, workflow.version))
            }
            className="mt-2 rounded bg-red-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"
          >
            {needsVerification ? "去强验证" : "提交转账"}
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

      {stable && (
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

      {error && <p className="mt-2 text-xs text-red-700">{error}</p>}
      {cancellable && (
        <button
          disabled={busy}
          onClick={() => void cancel()}
          className="mt-3 text-xs font-semibold text-slate-500 underline disabled:opacity-50"
        >
          取消
        </button>
      )}
    </section>
  );
}
