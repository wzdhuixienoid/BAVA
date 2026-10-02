import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import "./tsx-loader.mjs";
import { statuses, statusDisplay } from "../lib/presentation/status.ts";
import { errorDisplay } from "../lib/presentation/errors.ts";
import { isConfirmedWorkflow, responseState } from "../features/conversation/timeline.ts";
const { RiskDetails } = await import("../features/workflows/RiskDetails.tsx");
const { TransferWorkflowCard } = await import("../features/workflows/transfer/TransferWorkflowCard.tsx");
const { ConditionCard } = await import("../features/plans/ConditionCard.tsx");
const { PlanCard } = await import("../features/plans/PlanCard.tsx");
const { SubscriptionSummaryCard } = await import("../features/subscriptions/SubscriptionSummaryCard.tsx");
const { SubscriptionCancellationCard } = await import("../features/workflows/subscriptions/SubscriptionCancellationCard.tsx");
const { WorkflowReceipt } = await import("../features/results/WorkflowReceipt.tsx");
const { ResultsPanel } = await import("../features/results/ResultsPanel.tsx");
const render = (component, props) => renderToStaticMarkup(createElement(component, props));
const risk = {
  level: "RED", requested_amount: "600.00", currency: "CNY", daily_successful_total: "600.00",
  daily_in_flight_exposure: "0.00", projected_daily_total: "1200.00", threshold: "1000.00",
  requested_amount_display: "¥600.00", daily_successful_total_display: "¥600.00", daily_in_flight_exposure_display: "¥0.00",
  projected_daily_total_display: "¥1,200.00", threshold_display: "¥1,000.00", business_date: "2026-10-02",
  required_approval: true, required_reauthentication: true, reason_codes: ["RISK_ESCALATED_AT_COMMIT"],
};
const decision = { predicate: "ACCOUNT_BALANCE_AT_LEAST", actual_value: "3000", threshold_value: "4000", actual_display: "¥3,000.00", threshold_display: "¥4,000.00", currency: "CNY", outcome: "FALSE", source_step_id: "a", evaluated_at: "2026-10-02T08:00:00Z" };
const workflow = { workflow_id: "w", workflow_type: "TRANSFER", status: "COMMITTING", version: 1, state: { draft: {}, risk_decision: risk }, operation_summary: { operation_id: "o", status: "UNKNOWN" }, presentation: { business_success: false, stages: [{ key: "provider", label: "Provider 处理", status: "UNKNOWN" }] } };

test("600 transfer with backend RED exposure remains RED and shows required reauthentication", () => {
  const html = render(RiskDetails, { risk });
  assert.match(html, /RED · 红色/); assert.doesNotMatch(html, /YELLOW/);
  assert.match(html, /¥600\.00/); assert.match(html, /¥1,200\.00/); assert.match(html, /需要强身份验证/);
  assert.match(html, /2026-10-02/);
});
test("condition FALSE uses backend decision even if actual would satisfy threshold", () => {
  const html = render(ConditionCard, { decision: { ...decision, actual_value: "5000", actual_display: "¥5,000.00" }, sourceLabel: "步骤 1" });
  assert.match(html, /FALSE/); assert.match(html, /¥5,000\.00/); assert.doesNotMatch(html, />TRUE</);
});
test("UNKNOWN operation shows confirming result and never creates success receipt", () => {
  const html = render(TransferWorkflowCard, { workflow, onRefresh: async () => {} });
  assert.match(html, /结果确认中/); assert.doesNotMatch(html, /转账成功|转账已完成/);
  assert.equal(isConfirmedWorkflow(workflow), false); assert.equal(render(WorkflowReceipt, { workflow }), "");
});
test("Task COMPLETED with pending review is not business success", () => {
  const pending = { ...workflow, status: "READY_FOR_REVIEW", operation_summary: null };
  assert.equal(isConfirmedWorkflow(pending), false);
  assert.equal(responseState({ plans: [], tasks: [{ status: "COMPLETED" }], workflows: [pending] }).label, "等待你的操作");
  assert.doesNotMatch(render(TransferWorkflowCard, { workflow: pending, onRefresh: async () => {} }), /转账成功/);
});
test("real completion index excludes UNKNOWN and a pending workflow", () => {
  const html = render(ResultsPanel, { reports: [], workflows: [workflow, { ...workflow, workflow_id: "pending", status: "READY_FOR_REVIEW", operation_summary: null }], onLocateResult: () => {} });
  assert.doesNotMatch(html, /在对话中查看：转账/);
  assert.match(html, /已完成事件/);
  assert.match(html, />0</);
});
test("FALSE branch shows persisted skipped guarded step and real dependency", () => {
  const step = { step_id: "c", step_key: "condition", display_title: "余额条件", step_kind: "CONDITION", status: "COMPLETED", capability: null, condition_decision: decision, depends_on: ["a"] };
  const plan = { plan_id: "p", goal_summary: "检查后转账", status: "COMPLETED", steps: [{ step_id: "a", display_title: "查余额", status: "COMPLETED", step_kind: "CAPABILITY", capability: "ACCOUNT_QUERY", depends_on: [] }, step, { step_id: "w", display_title: "转账", status: "SKIPPED", step_kind: "CAPABILITY", capability: "TRANSFER_WORKFLOW", depends_on: ["c"], guard_condition_step_id: "c", error_code: "CONDITION_NOT_MET" }] };
  const html = render(PlanCard, { plan, workflows: [], onRefresh: async () => {} });
  assert.match(html, /计划依赖图/); assert.match(html, /FALSE/); assert.match(html, /已跳过/); assert.match(html, /Guard：步骤 2/); assert.doesNotMatch(html, /转账成功/);
});
test("DETECTED_ONLY capability false never exposes executable cancellation", () => {
  const html = render(SubscriptionSummaryCard, { snapshot: { subscriptions: [{ merchant: "检测商户", management_type: "DETECTED_ONLY", status: "ACTIVE", billing_interval: "MONTHLY", last_charge_date: "2026-08-01", last_charge_display: "¥50.00", monthly_cost_display: "¥50.00", annual_projected_cost_display: "¥600.00", currency: "CNY", cancellable: false }], monthly_cost_by_currency: [], price_changes: [] } });
  assert.match(html, /仅检测/); assert.match(html, /¥600\.00/); assert.doesNotMatch(html, /发起取消确认|取消按钮/);
  const cancellation = render(SubscriptionCancellationCard, { workflow: { ...workflow, workflow_type: "SUBSCRIPTION_CANCEL", risk_level: "YELLOW", status: "WAITING_FOR_INPUT", presentation: null, state: { required_input: { message: "请选择订阅", options: [{ merchant: "检测商户", management_type: "DETECTED_ONLY", subscription_id: "reference-only", cancellable: false, amount: "50.00", currency: "CNY" }] } } }, onRefresh: async () => {} });
  assert.doesNotMatch(cancellation, /<button[^>]*>选择<\/button>/);
});
test("central Chinese presentation covers all main persisted status families", () => {
  for (const status of ["WAITING_USER", "WAITING_EXTERNAL", "READY_FOR_REVIEW", "REAUTH_REQUIRED", "READY_FOR_COMMIT", "COMMITTING", "SUCCEEDED", "FAILED", "UNKNOWN", "WRITE_LOCKED", "SKIPPED", "PAUSED", "APPROVED", "VERIFIED", "CONSUMED", "SUBMITTED", "CREATED", "EXPIRED", "INVALIDATED", "INTERRUPTED", "ACTIVE"]) {
    const display = statusDisplay(status);
    assert.notEqual(display.label, status); assert.ok(display.description); assert.ok(display.icon); assert.ok(display.tone);
  }
  assert.equal(statusDisplay("future_unknown").label, "状态待同步");
  assert.ok(Object.keys(statuses).length >= 28);
});
test("security action failures use Chinese explanations without changing the server code", () => {
  assert.match(errorDisplay("WRITE_LOCKED"), /写操作已临时锁定/);
  assert.match(errorDisplay("SECURITY_WRITE_LOCKED"), /写操作已临时锁定/);
  assert.match(errorDisplay("REAUTH_FAILED"), /身份验证未通过/);
  assert.match(errorDisplay("TRANSFER_RISK_CURRENCY_UNSUPPORTED"), /仅支持 CNY/);
  assert.equal(errorDisplay("new_domain_error"), "new_domain_error");
});
