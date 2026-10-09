import assert from "node:assert/strict";
import test from "node:test";
import {createElement} from "react";
import {renderToStaticMarkup} from "react-dom/server";
import "./tsx-loader.mjs";
const {groupSchedules,ScheduleTaskCard} = await import("../features/schedules/TaskCards.tsx");
const row = {schedule_id:"one",workflow_id:"w1",series_id:"series",occurrence_index:1,status:"CANCELLED",series_revoked:true,created_at:"2026-10-08T00:00:00Z",scheduled_for:"2026-11-01T01:00:00Z",task_title:"给青禾物业转账 ¥100.00",remark:"物业费",recurrence:{day:1,count:3}};
const rows=[{...row,schedule_id:"three",workflow_id:"w3",occurrence_index:3,scheduled_for:"2027-01-01T01:00:00Z"},{...row,schedule_id:"two",workflow_id:"w2",occurrence_index:2,scheduled_for:"2026-12-01T01:00:00Z"},row];
const render=group=>renderToStaticMarkup(createElement(ScheduleTaskCard,{group,selected:null,onRefresh:async()=>{},onSelect:()=>{},onRevoke:()=>{}}));
test("one cycle has one task card with chronological periods and task before time",()=>{
 const groups=groupSchedules(rows);assert.equal(groups.length,1);assert.deepEqual(groups[0].rows.map(r=>r.occurrence_index),[1,2,3]);
 const html=render(groups[0]);assert.equal((html.match(/<article/g)||[]).length,1);assert.equal((html.match(/<h2/g)||[]).length,1);assert.equal((html.match(/<li/g)||[]).length,3);
 assert.ok(html.indexOf("给青禾物业转账")<html.indexOf("执行时间："));assert.match(html,/查看 3 期计划与状态/);assert.match(html,/2026-11-01 09:00:00 至 2027-01-01 09:00:00/);assert.doesNotMatch(html,/撤销后续周期授权/);
});
test("independent schedules with identical contents are never merged",()=>{
 const singles=[{...row,series_id:null,schedule_id:"single1"},{...row,series_id:null,schedule_id:"single2"}];
 assert.equal(groupSchedules([...rows,...singles]).length,3);
});
test("revoked cycle preserves UNKNOWN original-operation access and successful evidence",()=>{
 const mixed=[{...rows[0],status:"UNKNOWN",operation_id:"op"},{...rows[1],status:"SUCCEEDED"},row];
 const html=render(groupSchedules(mixed)[0]);assert.match(html,/结果确认中/);assert.match(html,/查询原操作/);assert.match(html,/付款成功 1 期/);assert.doesNotMatch(html,/全部付款成功/);
 const escaped=render(groupSchedules([{...row,remark:"<script>备注</script>"}])[0]);assert.match(escaped,/&lt;script&gt;/);assert.doesNotMatch(escaped,/<script>/);
});
test("delete is offered only for entirely cancelled tasks without operations",()=>{
 const renderDelete=items=>renderToStaticMarkup(createElement(ScheduleTaskCard,{group:groupSchedules(items)[0],selected:null,onRefresh:async()=>{},onSelect:()=>{},onRevoke:()=>{},onDelete:()=>{}}));
 assert.match(renderDelete(rows),/删除预约/);
 assert.doesNotMatch(renderDelete([{...row,status:'SCHEDULED'}]),/删除预约/);
 assert.doesNotMatch(renderDelete([{...row,status:'UNKNOWN',operation_id:'op'}]),/删除预约/);
 assert.doesNotMatch(renderDelete([{...row,operation_id:'op'}]),/删除预约/);
});
