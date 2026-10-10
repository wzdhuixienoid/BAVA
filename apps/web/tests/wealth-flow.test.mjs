import assert from "node:assert/strict";
import test from "node:test";
import {createElement} from "react";
import {renderToStaticMarkup} from "react-dom/server";
import "./tsx-loader.mjs";
const {WealthWorkflowCard, WealthProductCard} = await import("../features/wealth/WealthCards.tsx");
const {isConfirmedWorkflow} = await import("../features/conversation/timeline.ts");
const base = {workflow_id:"w",source_task_id:"t",workflow_type:"WEALTH_PURCHASE",version:3,status:"READY_FOR_REVIEW",state:{},presentation:{business_success:false,stages:[],wealth_state:{draft:{direction:"PURCHASE",product_id:"p",account_id:"a",quantity:"1000"},review:{name:"演示稳健优选",quantity_display:"1,000.00 元",fee_display:"1.00 元（估算）",shares_display:"999.123456 份（估算）",net_display:"999.00 元（估算）",trade_date:"2026-10-09",confirm_at:"2026-10-12T10:00:00+08:00",settle_at:"2026-10-12T10:00:00+08:00",notice:"按未来交易日净值成交，核对金额仅为估算。受理后不可撤单。",sources:["/api/v1/wealth/documents/p:v1:1"]}}}};
const render = workflow => renderToStaticMarkup(createElement(WealthWorkflowCard,{workflow,onRefresh:async()=>{}}));
test("wealth review uses backend estimates and dates, sources and explicit confirmation",()=>{
 const html=render(base);
 for (const text of ["1,000.00 元","1.00 元（估算）","999.123456 份（估算）","未来交易日净值","2026-10-12 10:00:00","查看资料","我已核对，确认交易"]) assert.ok(html.includes(text),text);
 assert.ok(!html.includes("提交申购"));
});
test("wealth strong verification gates submit",()=>{
 const html=render({...base,status:"REAUTH_REQUIRED"});
 assert.ok(html.includes("开始身份验证")); assert.ok(!html.includes("提交申购"));
 assert.match(render({...base,status:"READY_FOR_COMMIT",reauth_summary:{status:"VERIFIED"}}),/>提交申购</);
 assert.match(render({...base,status:"READY_FOR_COMMIT"}),/<button disabled=""[^>]*>提交申购/);
});
test("waiting and unknown never become success or offer cancellation",()=>{
 const waiting={...base,status:"COMMITTING",operation_summary:{status:"UNKNOWN"}};
 assert.equal(isConfirmedWorkflow(waiting),false); assert.match(render(waiting),/结果确认中/);
 assert.ok(!render(waiting).includes("取消草稿"));
 assert.equal(isConfirmedWorkflow({...base,status:"SUCCEEDED",presentation:{...base.presentation,business_success:true}}),true);
});
test("redeem uses original holding account and estimated receipt",()=>{
 const html=render({...base,workflow_type:"WEALTH_REDEEM",presentation:{...base.presentation,wealth_state:{...base.presentation.wealth_state,draft:{direction:"REDEEM"}}}});
 assert.match(html,/本人原付款账户/); assert.match(html,/赎回份额/); assert.match(html,/估算到账/);
});
test("mock product displays missing metrics and management fee clause",()=>{
 const html=renderToStaticMarkup(createElement(WealthProductCard,{product:{product_id:"p",name:"演示稳享日日",risk:"R1",minimum_display:"100.00 元",open_display:"每个模拟交易日15:00前",fees_display:"申购0.00% / 赎回0.00%",sources:[],nav_display:null,nav_date:null}}));
 assert.match(html,/暂无数据/); assert.match(html,/不另收持续管理费/); assert.match(html,/模拟/);
});
