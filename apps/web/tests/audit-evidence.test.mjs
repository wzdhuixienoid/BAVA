import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import "./tsx-loader.mjs";
const { AuditTimeline, AuditUnavailable } = await import("../features/audit/AuditTimeline.tsx");
const render = (trace) => renderToStaticMarkup(createElement(AuditTimeline, { trace }));
const risk = (level) => ({ level, reason_codes:[], currency:"CNY", requested_amount:"600", requested_amount_display:"¥600.00", projected_daily_total_display:level === "RED" ? "¥1,200.00" : "¥600.00", daily_successful_total_display:"¥600.00", daily_in_flight_exposure_display:"¥0.00", threshold_display:"¥1,000.00", required_approval:true, required_reauthentication:level === "RED", business_date:"2026-10-05" });
const entry = (sequence, summary, status, extra = {}) => ({ event_id:`e${sequence}`, sequence, timestamp:"2026-10-05T12:00:00Z", actor_type:"SYSTEM", status, decision_summary:summary, facts:[], related_resource_ids:{}, ...extra });
const base = { trace_id:"t", generated_at:"2026-10-05T12:00:00Z", history_note:"持久事实", entries:[], resources:[], write_evidence:{workflow_count:1,approval_count:1,operation_count:1,provider_submission_count:1,provider_ledger_count:0,business_success:false,no_write_started:false,skipped_write_step_ids:[]} };
test("audit timeline uses backend order and preserves risk escalation decisions", () => {
  // Intentionally nonchronological timestamps/sequence: rendering follows server order.
  const html = render({...base, entries:[entry(20,"第一次风险评估",null,{risk_decision:risk("YELLOW")}),entry(10,"提交时风险升级",null,{risk_decision:risk("RED")})]});
  assert.ok(html.indexOf("#20") < html.indexOf("#10"));
  assert.match(html,/YELLOW · 黄色/); assert.match(html,/RED · 红色/); assert.match(html,/¥1,200.00/);
});
test("UNKNOWN evidence survives final reconciliation success", () => {
  const html = render({...base,entries:[entry(1,"Provider 返回未知", "UNKNOWN"),entry(2,"开始 reconcile",null),entry(3,"Provider 已确认", "SUCCEEDED")],write_evidence:{...base.write_evidence,business_success:true}});
  assert.match(html,/结果确认中/); assert.ok(html.indexOf("Provider 返回未知") < html.indexOf("开始 reconcile"));
});
test("Condition FALSE, SKIPPED and zero-write facts ignore malicious TRUE prose", () => {
  const decision = {predicate:"ACCOUNT_BALANCE_AT_LEAST", source_step_id:"source", source_output_hash:"a".repeat(64),actual_value:"9000",threshold_value:"4000",actual_display:"¥9,000.00",threshold_display:"¥4,000.00",currency:"CNY",outcome:"FALSE",evaluated_at:"2026-10-05T12:00:00Z"};
  const html = render({...base,assistant_prose:"TRUE，转账成功",entries:[entry(1,"后端条件判断",null,{condition_decision:decision})],write_evidence:{...base.write_evidence,workflow_count:0,approval_count:0,operation_count:0,provider_submission_count:0,provider_ledger_count:0,no_write_started:true,skipped_write_step_ids:["write"]}});
  assert.match(html,/FALSE/); assert.match(html,/SKIPPED/); assert.match(html,/无 Workflow、无 Operation/); assert.doesNotMatch(html,/TRUE，转账成功/);
});
test("Mock reauthentication labeled and unrecognized secret fields never rendered", () => {
  const html = render({...base,token:"jwt-secret",otp:"otp-secret",reasoning:"scratchpad-secret",entries:[entry(1,"验证完成", "VERIFIED",{verification_code:"otp-secret", facts:[{key:"method",label:"验证方式",value:"Mock Reauthentication"}]})]});
  assert.match(html,/Mock Reauthentication/); assert.doesNotMatch(html,/jwt-secret|otp-secret|scratchpad-secret/);
});
test("cross-user unavailable never renders another owner's audit", () => {
  const html = renderToStaticMarkup(createElement(AuditUnavailable,{message:"Resource not found"}));
  assert.match(html,/审计链不可用/); assert.doesNotMatch(html,/业务成功|payload hash/);
});
test("fake success prose does not create authoritative audit success", () => {
  const html = render({...base,assistant_prose:"转账成功",task_status:"COMPLETED",entries:[entry(1,"等待用户确认", "READY_FOR_REVIEW")],write_evidence:{...base.write_evidence,operation_count:0,provider_submission_count:0}});
  assert.match(html,/尚不能显示写业务成功/); assert.doesNotMatch(html,/业务成功：Workflow/);
});
