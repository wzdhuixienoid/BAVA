import assert from "node:assert/strict";
import test from "node:test";
import {createElement} from "react";
import {renderToStaticMarkup} from "react-dom/server";
import "./tsx-loader.mjs";
const {AARequestCard} = await import("../features/aa/AARequestCard.tsx");
const {TransferWorkflowCard} = await import("../features/workflows/transfer/TransferWorkflowCard.tsx");
const render=(component,props)=>renderToStaticMarkup(createElement(component,props));
const review={source_account_display_name:"工资卡",source_account_masked_number:"****6688",payee_display_name:"李小雨",payee_masked_account:"****4815",payee_bank_name:"Mock银行",amount:"50.00",currency:"CNY",remark:"<script>餐费</script>",scheduled_for:"2026-10-09T01:00:00Z",execute_deadline:"2026-10-09T01:05:00Z",business_timezone:"Asia/Shanghai"};
test("appointment review binds Beijing time and distinguishes authorization from payment",()=>{
  const html=render(TransferWorkflowCard,{workflow:{workflow_id:"w",version:1,status:"READY_FOR_COMMIT",state:{draft:{schedule_id:"s",schedule_requested:true},review_payload:review}},onRefresh:async()=>{}});
  assert.match(html,/授权并创建预约/); assert.match(html,/2026-10-09 09:00:00/);assert.match(html,/不冻结余额/);assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>餐费/);
});
const collection={request_id:"a",created_at:"2026-10-08T00:00:00Z",version:1,status:"PARTIAL",is_initiator:true,snapshot:{total:"100.00",remark:"聚餐",deadline:"2026-10-15T00:00:00Z",collection_account:{display_name:"储蓄卡",masked_number:"****1024"}},receivable:"66.67",received:"33.34",outstanding:"33.33",self_paid:"33.33",shares:[{share_id:"one",display_name:"张三",amount:"33.34",status:"PAID",is_mine:false},{share_id:"two",display_name:"李四",amount:"33.33",status:"PENDING",is_mine:false},{share_id:"self",display_name:"我",amount:"33.33",status:"SELF_PAID",is_mine:true}]};
test("AA shows partial receipts and cancellation only for unpaid shares",()=>{
  const html=render(AARequestCard,{requestId:"a",initialRequest:collection});assert.match(html,/部分收款/);assert.match(html,/33\.34/);assert.match(html,/33\.33/);assert.equal((html.match(/撤回收款请求/g)||[]).length,1);assert.doesNotMatch(html,/核对并付款|已收齐|Asia\/Shanghai/);assert.match(html,/2026-10-15 08:00:00/);assert.match(html,/无需在这里付款/);assert.match(html,/自己承担/);
});
test("AA UNKNOWN exposes original payment detail and never counts as collected",()=>{
 const html=render(AARequestCard,{requestId:"a",initialRequest:{...collection,received:"0.00",shares:[{...collection.shares[0],is_mine:true,status:"UNKNOWN",workflow_id:"w"}]}});assert.match(html,/查询原操作/);assert.doesNotMatch(html,/已收齐|撤回收款请求/);
});

test("AA participant has an independent payment entry for their pending share",()=>{
 const html=render(AARequestCard,{requestId:"a",initialRequest:{...collection,is_initiator:false,shares:[{...collection.shares[1],is_mine:true}]}});
 assert.match(html,/选择我的付款账户/);assert.match(html,/核对并付款/);assert.match(html,/拒绝付款/);assert.doesNotMatch(html,/撤回收款请求|无需在这里付款/);
});

test("monthly review shows all dates and exact finite authorization total",()=>{
 const recurrence={frequency:"MONTHLY",day:1,hour:9,minute:0,count:3,occurrences:["2026-11-01T01:00:00Z","2026-12-01T01:00:00Z","2027-01-01T01:00:00Z"]};
 const html=render(TransferWorkflowCard,{workflow:{workflow_id:"monthly",version:1,status:"READY_FOR_COMMIT",state:{draft:{schedule_id:"s",schedule_requested:true,recurrence},review_payload:{...review,amount:"0.10",recurrence}}},onRefresh:async()=>{}});
 assert.match(html,/授权并创建周期转账/);assert.match(html,/共 3 次/);assert.match(html,/¥0.30/);
 for(const date of ["2026-11-01 09:00:00","2026-12-01 09:00:00","2027-01-01 09:00:00"])assert.ok(html.includes(date));
 assert.doesNotMatch(html,/Asia\/Shanghai|年11月/);
});
