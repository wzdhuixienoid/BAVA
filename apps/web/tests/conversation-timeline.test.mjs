import assert from "node:assert/strict";
import test from "node:test";
import { buildConversationTurns, isConfirmedWorkflow, responseState } from "../features/conversation/timeline.ts";

const message = (message_id, role) => ({ message_id, role, content: message_id });
const task = (task_id, source, answer, status = "COMPLETED") => ({
  task_id, status, input: source ? { message_id: source } : {},
  output: answer ? { assistant_message_id: answer } : null,
});
const build = (resources) => buildConversationTurns({ messages: [], tasks: [], plans: [], workflows: [], reports: [], ...resources });

test("processing and completed answer retain the same assistant turn", () => {
  const pending = build({ messages: [message("u1", "USER")], tasks: [task("t1", "u1", null, "RUNNING")] });
  const completed = build({ messages: [message("u1", "USER"), message("a1", "ASSISTANT")], tasks: [task("t1", "u1", "a1")] });
  assert.equal(pending.length, 1);
  assert.equal(completed.length, 1);
  assert.equal(pending[0].id, completed[0].id);
  assert.equal(completed[0].replies[0].message_id, "a1");
});

test("concurrent replies are associated by source IDs even when they finish out of order", () => {
  const turns = build({
    messages: [message("u1", "USER"), message("u2", "USER"), message("a2", "ASSISTANT"), message("a1", "ASSISTANT")],
    tasks: [task("t1", "u1", "a1"), task("t2", "u2", "a2")],
  });
  assert.deepEqual(turns.map((turn) => [turn.user.message_id, turn.replies.map((reply) => reply.message_id)]), [["u1", ["a1"]], ["u2", ["a2"]]]);
  assert.equal(turns.flatMap((turn) => turn.replies).length, 2);
});

test("legacy messages and tasks can share a reply without an answer ID", () => {
  const [turn] = build({ messages: [message("u1", "USER"), message("a1", "ASSISTANT")], tasks: [task("t1", "u1")] });
  assert.equal(turn.tasks[0].task_id, "t1");
  assert.equal(turn.replies[0].message_id, "a1");
});

test("answer linkage recovers a legacy task whose input lacks the message ID", () => {
  const turns = build({ messages: [message("u1", "USER"), message("a1", "ASSISTANT")], tasks: [task("t1", null, "a1")] });
  assert.equal(turns.length, 1);
  assert.equal(turns[0].tasks[0].task_id, "t1");
});

test("all persisted results stay in the conversation even when task output is cleared", () => {
  const [turn] = build({
    messages: [message("u1", "USER")], tasks: [task("t1", "u1", null, "RUNNING")],
    reports: [{ report_id: "r1", source_task_id: "t1" }, { report_id: "r2", source_task_id: "t1" }],
    plans: [{ plan_id: "p1", source_task_id: "t1", status: "RUNNING" }],
    workflows: [{ workflow_id: "w1", source_task_id: "t1", status: "READY_FOR_REVIEW" }],
  });
  assert.deepEqual(turn.reports.map((report) => report.report_id), ["r1", "r2"]);
  assert.equal(turn.plans.length, 1);
  assert.equal(turn.workflows.length, 1);
});

test("orphaned artifacts have a central response so every index entry can be located", () => {
  const [turn] = build({
    reports: [{ report_id: "r1", source_task_id: "old-task" }],
    workflows: [{ workflow_id: "w1", source_task_id: "old-task" }],
  });
  assert.equal(turn.tasks.length, 0);
  assert.equal(turn.reports.length, 1);
  assert.equal(turn.workflows.length, 1);
});

test("a completed draft task does not complete a pending banking workflow", () => {
  const [turn] = build({ tasks: [task("t1", null)], workflows: [{ source_task_id: "t1", status: "READY_FOR_REVIEW" }] });
  assert.equal(responseState(turn).label, "等待你的操作");
});

test("a success receipt requires both workflow and operation confirmation", () => {
  assert.equal(isConfirmedWorkflow({ status: "SUCCEEDED", operation_summary: { status: "UNKNOWN" } }), false);
  assert.equal(isConfirmedWorkflow({ status: "COMMITTING", operation_summary: { status: "SUCCEEDED" } }), false);
  assert.equal(isConfirmedWorkflow({ status: "SUCCEEDED", operation_summary: { status: "SUCCEEDED" } }), true);
  const [turn] = build({ tasks: [task("t1", null)], workflows: [{ source_task_id: "t1", status: "SUCCEEDED", operation_summary: { status: "UNKNOWN" } }] });
  assert.equal(responseState(turn).active, true);
  assert.equal(responseState(turn).label, "正在等待银行确认结果");
});

test("future cycle occurrences stay in the cycle review, UNKNOWN occurrence stays visible",()=>{
 const child={...task("child",null,null),task_type:"recurring_transfer_occurrence"};
 const workflow={workflow_id:"future",source_task_id:"child",status:"READY_FOR_COMMIT",operation_summary:null};
 assert.equal(build({tasks:[child],workflows:[workflow]}).length,0);
 const started=build({tasks:[child],workflows:[{...workflow,status:"COMMITTING",operation_summary:{status:"UNKNOWN"}}]});
 assert.equal(started.length,1);assert.equal(started[0].workflows[0].operation_summary.status,"UNKNOWN");
});

for (const direction of ["PURCHASE", "REDEEM"]) {
 test(`accepted wealth ${direction} finishes response without completing financial operation`,()=>{
  const workflow={workflow_type:`WEALTH_${direction}`,source_task_id:"t",status:"COMMITTING",operation_summary:{status:"UNKNOWN"},presentation:{business_success:false,wealth_state:{order_received:true,order_stage:direction==="REDEEM"?"CONFIRMED":"ACCEPTED"}}};
  const [turn]=build({tasks:[task("t",null,null,"WAITING_EXTERNAL")],workflows:[workflow]});
  assert.deepEqual(responseState(turn),{active:false,label:"申请已提交，成交后会通知你",failed:false});
  assert.equal(isConfirmedWorkflow(workflow),false);
  assert.equal(workflow.status,"COMMITTING");assert.equal(turn.tasks[0].status,"WAITING_EXTERNAL");
  assert.equal(responseState({...turn,tasks:[...turn.tasks,task("other",null,null,"RUNNING")]}).active,true);
  assert.equal(responseState({...turn,workflows:[...turn.workflows,{workflow_type:"TRANSFER",status:"COMMITTING"}]}).active,true);
  assert.equal(responseState({...turn,workflows:[{...workflow,presentation:{wealth_state:{order_received:false}}}]}).active,true);
 });
}
