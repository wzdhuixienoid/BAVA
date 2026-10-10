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
  assert.match(html, /到商户管理/); assert.match(html, /¥600\.00/); assert.doesNotMatch(html, /发起取消确认|取消按钮/);
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


test("resume uses strong verification and never labels the result cancelled", () => {
  const resume = { ...workflow, workflow_type: "SUBSCRIPTION_RESUME", risk_level: "RED", status: "REAUTH_REQUIRED", state: { draft: { action: "SUBSCRIPTION_RESUME" }, review_payload: { merchant: "星幕视频", amount: "28.00", currency: "CNY" } }, presentation: null, operation_summary: null };
  const html = render(SubscriptionCancellationCard, { workflow: resume, onRefresh: async () => {} });
  assert.match(html, /订阅恢复工作流/); assert.match(html, /开始身份验证/); assert.doesNotMatch(html, /订阅已取消/);
});

test("historical subscription snapshots do not render an analysis card or fold the answer", async () => {
  const { AssistantTurn } = await import("../features/conversation/AssistantTurn.tsx");
  const html = render(AssistantTurn, { turn: { user: { message_id: "u1" }, tasks: [{ task_id: "snapshot-task", status: "COMPLETED", input: {}, output: { subscription_analysis_snapshot: { subscriptions: [], monthly_cost_by_currency: [], price_changes: [] } } }], plans: [], workflows: [], reports: [], replies: [{ message_id: "a1", role: "ASSISTANT", content: "详细信息可在左侧「订阅与代扣总览」查看。" }], }, activityRevision: 0, highlightedResult: null, onRefresh: async () => {} });
  assert.doesNotMatch(html, /订阅分析|助理说明/); assert.match(html, /以下是你的订阅情况/);
});

test("legacy confirmed draft never claims strong verification complete without evidence", () => {
  const html = render(TransferWorkflowCard, { workflow: { ...workflow, status: "READY_FOR_COMMIT", risk_decision: risk, reauth_summary: null, operation_summary: null, presentation: null, state: { draft: {}, risk_decision: risk, review_payload: { amount: "1.00", currency: "CNY" } } }, onRefresh: async () => {} });
  assert.match(html, /还需要完成强身份验证/); assert.match(html, /去强验证/); assert.doesNotMatch(html, /强身份验证已完成/);
});

test("payee query keeps only the text answer, including historical structured results", async () => {
  const { AssistantTurn } = await import("../features/conversation/AssistantTurn.tsx");
  const html = render(AssistantTurn, { turn: { user: { message_id: "u" }, tasks: [{ task_id: "payee-task", status: "COMPLETED", input: {}, output: { payee_results: [{ payees: [{ payee_id: "p", display_name: "张三", bank_name: "模拟银行", masked_account: "****1234", phone_alias: "" }] }] } }], plans: [], workflows: [], reports: [], replies: [{ message_id: "a", role: "ASSISTANT", content: "可转账收款人：张三 · ****1234" }] }, activityRevision: 0, highlightedResult: null, onRefresh: async () => {} });
  assert.equal((html.match(/张三/g) ?? []).length, 1);
  assert.equal((html.match(/1234/g) ?? []).length, 1);
  assert.doesNotMatch(html, /助理说明/);
});

test("recipient step provides existing and new payee shortcuts with distinct same-name options", () => {
  const draft = { ...workflow, conversation_id: "chat-1", status: "WAITING_FOR_INPUT", operation_summary: null, state: { draft: {}, required_input: { type: "PAYEE_SELECTION", message: "请选择收款人" } }, presentation: { stages: [], payee_options: [{ payee_id: "p1", display_name: "张三", bank_name: "甲银行", masked_account: "****1001", phone_alias: "" }, { payee_id: "p2", display_name: "张三", bank_name: "乙银行", masked_account: "****1002", phone_alias: "" }] } };
  const html = render(TransferWorkflowCard, { workflow: draft, onRefresh: async () => {} });
  assert.match(html, /选择已有收款人/); assert.match(html, /新增收款人/);
  assert.match(html, /payees\?conversation=chat-1&amp;workflow=w/);
  assert.match(html, /选择张三，甲银行，\*\*\*\*1001/); assert.match(html, /选择张三，乙银行，\*\*\*\*1002/);
});

test("ordinary spending answers stay visible without an automatic dashboard, including saved outputs", async () => {
  const { AssistantTurn } = await import("../features/conversation/AssistantTurn.tsx");
  const html = render(AssistantTurn, { turn: { user: { message_id: "u" }, tasks: [{ task_id: "spending-task", status: "COMPLETED", input: {}, output: { analysis_snapshot: {}, financial_display: { period: "2026-09" } } }], plans: [], workflows: [], reports: [], replies: [{ message_id: "a", role: "ASSISTANT", content: "主要支出为 HOUSING 与 HEALTH。" }] }, activityRevision: 0, highlightedResult: null, onRefresh: async () => {} });
  assert.match(html, /主要支出为 住房 与 健康/);
  assert.doesNotMatch(html, /消费 Dashboard|助理说明|HOUSING|HEALTH/);
});

test("saved spending tables localize categories, accounts, timestamps and decimal ratios", async () => {
  const { localizeFinancialAnswer } = await import("../features/conversation/financialAnswer.ts");
  const content = "| 分类 | 金额 | 笔数 | 占比 |\n| --- | --- | --- | --- |\n| HOUSING | 6200.00 | 1 | 0.6718136258973317079777868075 |\n| OTHER | 0 | 1 | 0 |\n| FOOD | 1 | 1 | 1 |\n\n（share 为 0–1 的比例原值，未做换算。）\n2026-09-03T12:20:00Z HOUSING acc_salary CNY";
  const output = localizeFinancialAnswer(content, [{ analysis_snapshot: { top_transactions: { transactions: [{ account_id: "acc_salary", account_display: "工资卡" }] } } }]);
  assert.match(output, /占比 \(%\)/);
  assert.match(output, /67\.18%/);
  assert.match(output, /0\.00%/);
  assert.match(output, /100\.00%/);
  assert.match(output, /2026-09-03 20:20:00 住房 工资卡 人民币/);
  assert.equal(localizeFinancialAnswer("2026年08月03日 12:14:00（协调世界时）", []), "2026-08-03 20:14:00");
  assert.equal(localizeFinancialAnswer("2026-08-03T20:14:00+08:00", []), "2026-08-03 20:14:00");
  assert.equal(localizeFinancialAnswer("2026年08月03日 12:14:32（UTC）", []), "2026-08-03 20:14:32");
  assert.doesNotMatch(output, /share|HOUSING|acc_salary|T12|CNY/);
  assert.match(localizeFinancialAnswer("| 分类 | 占比 |\n| --- | --- |\n| FOOD | 0.99995 |", []), /100\.00%/);
});

test("legacy unsolicited anomaly analysis is identified instead of presented as the requested spending answer", async () => {
  const { AssistantTurn } = await import("../features/conversation/AssistantTurn.tsx");
  const props = { turn: { user: { message_id: "u", content: "分析我最近15天的消费" }, tasks: [{ task_id: "legacy", status: "COMPLETED", output: { transaction_anomaly_snapshot: {}, analysis_snapshot: { spending_summary: { period: "2026-09" } } } }], plans: [], reports: [], workflows: [], replies: [{ message_id: "a", role: "ASSISTANT", content: "不支持天数，所以做异常分析。" }] }, activityRevision: 0, highlightedResult: null, onRefresh: async () => {} };
  const html = render(AssistantTurn, props);
  assert.match(html, /这条历史回复误用了异常交易分析/);
  assert.doesNotMatch(html, /不支持天数|助理说明/);
});

test("anomaly presentation requires intent in the current request", async () => {
  const { requestsAnomalyAnalysis } = await import("../features/conversation/financialAnswer.ts");
  assert.equal(requestsAnomalyAnalysis("最近15天消费"), false);
  assert.equal(requestsAnomalyAnalysis("分析最近15天消费，不要查异常"), false);
  assert.equal(requestsAnomalyAnalysis("最近15天有没有异常交易"), true);
});

test("report check section is brief, grounded and omits currency and severity tables", async () => {
  const { SpendingReview } = await import("../features/reports/SpendingReview.tsx");
  const review = { status: "PARTIAL", message: "发现 4 笔值得核对的交易。", total_count: 4,
    notes: ["部分消费缺少足够历史。"], answer: "", items: [{ transaction_id: "t", occurred_at: "2026-10-06T12:06:00Z",
      merchant: "数码商户", amount_display: "999.00", reason: "短时重复扣款" }] };
  const html = render(SpendingReview, { review });
  assert.match(html, /值得核对的交易|短时重复扣款|999\.00 元|2026-10-06 20:06:00/);
  assert.match(html, /部分消费缺少足够历史|不代表已确认欺诈/);
  assert.doesNotMatch(html, /<table|HIGH|币种|人民币|¥/);
  assert.equal(render(SpendingReview, {}), "");
});

test("ordinary assistant keeps spending answer and brief automatic check together", async () => {
  const { AssistantTurn } = await import("../features/conversation/AssistantTurn.tsx");
  const html = render(AssistantTurn, { turn: { user: { message_id: "u", content: "近期消费情况" },
    tasks: [{ task_id: "t", status: "COMPLETED", output: { analysis_snapshot: { spending_summary: { spending_review: {} } } } }],
    plans: [], workflows: [], reports: [], replies: [{ message_id: "a", role: "ASSISTANT",
      content: "消费总额为 1000.00 元。\n\n### 值得核对的交易\n短时重复扣款。" }] },
    activityRevision: 0, highlightedResult: null, onRefresh: async () => {} });
  assert.match(html, /消费总额为 1000\.00 元|短时重复扣款/);
  assert.equal((html.match(/值得核对的交易/g) ?? []).length, 1);
  assert.doesNotMatch(html, /历史回复误用|异常交易分析|助理说明/);
});

test("report transactions and scoped footer use Chinese account names without changing amounts", async () => {
  const { TopTransactions } = await import("../features/reports/TopTransactions.tsx");
  const html = render(TopTransactions, { transactions: [{ transaction_id: "t", occurred_at: "2026-09-03T12:20:00Z", merchant: "公寓", description: "月租", category: "HOUSING", amount_display: "¥6,200.00", account_id: "acc_salary" }], accountNames: { acc_salary: "工资卡" } });
  assert.match(html, /工资卡/); assert.match(html, /¥6,200\.00/);
  assert.doesNotMatch(html, /acc_salary/);
});

test("report list separates deletion controls from navigation and shows restore in trash", async () => {
  const { ReportList } = await import("../features/reports/ReportList.tsx");
  const reports = [{ report_id: "r", period: "2026-09", headline: "消费结构", total_spending_display: "¥9,228.75", created_at: "2026-10-07T14:00:00Z", deleted_at: "2026-10-07T15:00:00Z" }];
  const html = render(ReportList, { reports, onDelete: () => {} });
  assert.match(html, /aria-label="删除2026年9月消费报告"/);
  assert.doesNotMatch(html, /<a[^>]*>(?:(?!<\/a>)[\s\S])*<button/);
  const trash = render(ReportList, { reports, deleted: true, onRestore: () => {} });
  assert.match(trash, /恢复报告/); assert.doesNotMatch(trash, /href=/);
});

test("deleted report task outputs do not recreate a report card in the conversation", async () => {
  const { AssistantTurn } = await import("../features/conversation/AssistantTurn.tsx");
  const html = render(AssistantTurn, { turn: { user: { message_id: "u", content: "生成消费报告" }, tasks: [{ task_id: "t", status: "COMPLETED", output: { report_id: "deleted-r", report_deleted: true } }], plans: [], reports: [], workflows: [], replies: [{ message_id: "a", role: "ASSISTANT", content: "报告已生成。" }] }, activityRevision: 0, highlightedResult: null, onRefresh: async () => {} });
  assert.doesNotMatch(html, /href="\/reports\/deleted-r"/);
});

test("anomaly analysis is a single visible assistant answer without a separate card or folded copy", async () => {
  const { AssistantTurn } = await import("../features/conversation/AssistantTurn.tsx");
  const content = "## 异常交易分析\n\n| 日期 | 金额 | 严重度 | 金额倍数 |\n| --- | --- | --- | --- |\n| 2026-10-07 20:00:00 | 8600.00 | 高 | 190.90 |";
  const html = render(AssistantTurn, { turn: { user: { message_id: "u", content: "近一年有什么异常交易吗" }, tasks: [{ task_id: "t", status: "COMPLETED", output: { transaction_anomaly_snapshot: { analysis_period_started_at: "2025-10-07T15:05:00Z", analysis_period_ended_at: "2026-10-07T15:05:00Z" }, transaction_anomaly_answer: content } }], plans: [], workflows: [], reports: [], replies: [{ message_id: "a", role: "ASSISTANT", content: "旧的重复回答。" }] }, activityRevision: 0, highlightedResult: null, onRefresh: async () => {} });
  assert.equal((html.match(/异常交易分析/g) ?? []).length, 1);
  assert.match(html, /8600\.00/); assert.match(html, /190\.90/);
  assert.doesNotMatch(html, /助理说明|旧的重复回答|violet|¥|HIGH/);
});
