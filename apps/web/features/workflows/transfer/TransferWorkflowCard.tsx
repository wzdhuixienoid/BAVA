"use client";

import { useState } from "react";
import type { components } from "@banking/api-client";
import { api } from "@/lib/api/client";

type Workflow = components["schemas"]["Workflow"];
type TransferRiskDecision = components["schemas"]["TransferRiskDecision"];

type PayeeOption = {
  payee_id: string;
  display_name: string;
  bank_name: string;
  masked_account: string;
  phone_alias: string;
};

type AccountOption = {
  account_id: string;
  display_name: string;
  masked_number: string;
  currency: string;
  available_balance: string;
};

type TransferState = {
  draft: {
    recipient_query?: string | null;
    payee_id?: string | null;
    amount?: string | null;
    source_account_id?: string | null;
  };
  required_input?: {
    type: "PAYEE_SELECTION" | "SOURCE_ACCOUNT_SELECTION" | "AMOUNT" | "RECIPIENT_QUERY";
    message: string;
    options: Array<PayeeOption | AccountOption>;
  } | null;
  validation?: {
    is_valid: boolean;
    issues: Array<{ code: string; message: string }>;
  } | null;
  review_payload?: {
    source_account_display_name: string;
    source_account_masked_number: string;
    payee_display_name: string;
    payee_bank_name: string;
    payee_masked_account: string;
    amount: string;
    currency: string;
  } | null;
  payee_options?: PayeeOption[];
  source_account_options?: AccountOption[];
};

function isPayee(option: PayeeOption | AccountOption): option is PayeeOption {
  return "payee_id" in option;
}

function money(value: string, currency: string) {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(Number(value));
}

function expiresAt(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(new Date(value));
}

function ReviewDetails({ state }: { state: TransferState }) {
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
      <dd className="font-semibold">{money(review.amount, review.currency)}</dd>
      <dt className="text-slate-500">币种</dt>
      <dd>{review.currency}</dd>
    </dl>
  );
}

function RiskDetails({ risk }: { risk: TransferRiskDecision }) {
  const red = risk.level === "RED";
  const escalated = risk.reason_codes.includes("RISK_ESCALATED_AT_COMMIT");
  return (
    <div
      className={`mt-3 rounded-md border p-3 ${
        red ? "border-red-300 bg-red-50" : "border-amber-300 bg-amber-50"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <p className={`text-sm font-bold ${red ? "text-red-800" : "text-amber-800"}`}>
          风险等级：{red ? "红色" : "黄色"}
        </p>
        <span className="rounded-full bg-white px-2 py-1 text-[10px] font-semibold">
          {red ? "强验证" : "用户确认"}
        </span>
      </div>
      {escalated && (
        <p className="mt-2 rounded bg-red-100 p-2 text-xs font-semibold leading-5 text-red-800">
          风险等级已升级：今日累计转账金额发生变化，本次操作现在需要强验证。
        </p>
      )}
      <dl className="mt-3 grid grid-cols-[112px_1fr] gap-y-1 text-xs">
        <dt className="text-slate-500">本笔转账</dt>
        <dd>{money(risk.requested_amount, risk.currency)}</dd>
        <dt className="text-slate-500">今日已成功</dt>
        <dd>{money(risk.daily_successful_total, risk.currency)}</dd>
        <dt className="text-slate-500">今日执行中</dt>
        <dd>{money(risk.daily_in_flight_exposure, risk.currency)}</dd>
        <dt className="text-slate-500">预计日累计</dt>
        <dd className="font-semibold">{money(risk.projected_daily_total, risk.currency)}</dd>
      </dl>
      <div className="mt-3 space-y-1 text-xs text-slate-700">
        <p>✓ 需要用户确认</p>
        <p>{risk.required_reauthentication ? "✓ 需要强身份验证（模拟）" : "○ 无需强验证"}</p>
      </div>
    </div>
  );
}

export function TransferWorkflowCard({
  workflow,
  onRefresh,
}: {
  workflow: Workflow;
  onRefresh: () => Promise<void>;
}) {
  const state = workflow.state as TransferState;
  const required = state.required_input;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [amount, setAmount] = useState("");
  const [recipientQuery, setRecipientQuery] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [editing, setEditing] = useState(false);

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setVerificationCode("");
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
        <span className="rounded-full bg-white px-2 py-1 text-[10px] font-semibold text-slate-600">
          {workflow.status}
        </span>
      </div>

      {workflow.risk_decision && <RiskDetails risk={workflow.risk_decision} />}

      {workflow.status === "WAITING_FOR_INPUT" && required?.type === "RECIPIENT_QUERY" && (
        <div className="mt-3">
          <label className="text-sm font-semibold text-slate-900" htmlFor={`recipient-${workflow.workflow_id}`}>
            收款人
          </label>
          <div className="mt-2 flex gap-2">
            <input
              id={`recipient-${workflow.workflow_id}`}
              value={recipientQuery}
              onChange={(event) => setRecipientQuery(event.target.value)}
              className="min-w-0 flex-1 rounded border border-amber-200 bg-white px-2 py-1.5 text-sm"
              placeholder="姓名或手机别名"
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
              className="rounded bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
            >
              保存
            </button>
          </div>
        </div>
      )}

      {workflow.status === "WAITING_FOR_INPUT" && required?.type === "PAYEE_SELECTION" && (
        <div className="mt-3 space-y-2">
          <p className="text-sm font-semibold text-slate-900">请选择收款人</p>
          {required.options.filter(isPayee).map((option) => (
            <div key={option.payee_id} className="rounded-md border border-amber-200 bg-white p-2">
              <p className="text-sm font-semibold text-slate-900">{option.display_name}</p>
              <p className="text-xs text-slate-500">
                {option.bank_name} · {option.masked_account} · {option.phone_alias}
              </p>
              <button
                disabled={busy}
                onClick={() =>
                  void act(() =>
                    api.selectPayee(workflow.workflow_id, option.payee_id, workflow.version),
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

      {workflow.status === "WAITING_FOR_INPUT" && required?.type === "SOURCE_ACCOUNT_SELECTION" && (
        <div className="mt-3 space-y-2">
          <p className="text-sm font-semibold text-slate-900">请选择付款账户</p>
          {(required.options as AccountOption[]).map((option) => (
            <div key={option.account_id} className="rounded-md border border-amber-200 bg-white p-2">
              <p className="text-sm font-semibold text-slate-900">{option.display_name}</p>
              <p className="text-xs text-slate-500">{option.masked_number}</p>
              <p className="mt-1 text-xs text-slate-700">
                可用余额 {money(option.available_balance, option.currency)}
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
          <ReviewDetails state={state} />
          <p className="mt-3 text-[11px] leading-5 text-slate-500">
            READY_FOR_REVIEW 仅表示当前草稿通过初步校验，不代表已批准，也不保证提交时余额仍然充足。
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

      {workflow.status === "REAUTH_REQUIRED" && state.review_payload && (
        <div className="mt-3 rounded-md border border-blue-200 bg-white p-3">
          <p className="text-sm font-semibold text-blue-900">转账信息已确认</p>
          <p className="mt-1 text-xs text-slate-600">需要完成强身份验证（模拟）后才能继续</p>
          <ReviewDetails state={state} />
          {workflow.approval_summary?.expires_at && (
            <p className="mt-2 text-[11px] text-slate-500">
              确认有效至 {expiresAt(workflow.approval_summary.expires_at)}
            </p>
          )}
          {workflow.reauth_summary?.status === "PENDING" ? (
            <div className="mt-3">
              <label className="text-xs font-semibold text-slate-800" htmlFor={`reauth-${workflow.workflow_id}`}>
                身份验证码
              </label>
              <div className="mt-2 flex gap-2">
                <input
                  id={`reauth-${workflow.workflow_id}`}
                  type="password"
                  autoComplete="one-time-code"
                  value={verificationCode}
                  onChange={(event) => setVerificationCode(event.target.value)}
                  className="min-w-0 flex-1 rounded border border-blue-200 px-2 py-1.5 text-sm"
                  placeholder="输入验证码"
                />
                <button
                  disabled={busy || !verificationCode}
                  onClick={() =>
                    void act(() =>
                      api.verifyTransferReauthentication(
                        workflow.workflow_id,
                        workflow.reauth_summary!.reauth_id,
                        verificationCode,
                        workflow.version,
                      ),
                    )
                  }
                  className="rounded bg-blue-700 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
                >
                  验证
                </button>
              </div>
            </div>
          ) : (
            <button
              disabled={busy}
              onClick={() =>
                void act(() =>
                  api.startTransferReauthentication(workflow.workflow_id, workflow.version),
                )
              }
              className="mt-3 rounded bg-blue-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"
            >
              开始身份验证
            </button>
          )}
        </div>
      )}

      {workflow.status === "READY_FOR_COMMIT" && state.review_payload && (
        <div className="mt-3 rounded-md border border-indigo-200 bg-white p-3">
          <p className="text-sm font-semibold text-indigo-900">转账信息已确认</p>
          <p className="mt-1 text-sm font-semibold text-emerald-700">
            {workflow.risk_decision?.required_reauthentication
              ? "强身份验证已完成"
              : "用户确认已完成，无需强验证"}
          </p>
          <ReviewDetails state={state} />
          <p className="mt-3 rounded bg-amber-50 p-2 text-xs font-semibold text-amber-800">
            尚未提交转账
          </p>
          <p className="mt-2 text-[11px] leading-5 text-slate-500">
            READY_FOR_COMMIT 表示当前 payload 已批准并满足当前风险所需的安全控制。提交前会再次评估风险。
          </p>
          <p className="mt-3 text-xs font-semibold text-red-700">
            这一步将真正提交资金转账
          </p>
          <button
            disabled={busy}
            onClick={() =>
              void act(() => api.commitTransfer(workflow.workflow_id, workflow.version))
            }
            className="mt-2 rounded bg-red-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"
          >
            提交转账
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
          <ReviewDetails state={state} />
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
          <ReviewDetails state={state} />
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
              <div>
                <p className="text-xs font-semibold text-slate-700">更换收款人</p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {(state.payee_options ?? []).map((option) => (
                    <button
                      key={option.payee_id}
                      disabled={busy || state.draft.payee_id === option.payee_id}
                      onClick={() =>
                        void act(() =>
                          api.selectPayee(workflow.workflow_id, option.payee_id, workflow.version),
                        )
                      }
                      className="rounded border px-2 py-1 text-[11px] disabled:opacity-40"
                    >
                      {option.display_name} · {option.bank_name} · {option.masked_account}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-xs font-semibold text-slate-700">更换付款账户</p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {(state.source_account_options ?? []).map((option) => (
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
          {state.validation?.issues.map((issue) => (
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
