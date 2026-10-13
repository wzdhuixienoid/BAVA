import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import "./tsx-loader.mjs";
const { api } = await import("../lib/api/client.ts");
const { currentMonth } = await import("../lib/presentation/time.ts");
const { default: DashboardPage } = await import("../app/dashboard/page.tsx");
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.self = globalThis;
const snapshot = period => ({accounts:[], recent_transactions:[], as_of:"2026-10-12T12:00:00Z", risk_level:"GREEN", spending:{period, overview:{total_spending_display:"¥0.00",total_income_display:"¥0.00",transaction_count:0},period_comparison:null,category_breakdown:[],top_transactions:[]},anomalies:{analysis_period_started_at:"2026-09-12T12:00:00Z",analysis_period_ended_at:"2026-10-12T12:00:00Z",anomalies:[],insufficient_baseline:false}});
const text = n => typeof n === "string" ? n : (n?.children ?? []).map(text).join("");
test("current month follows Beijing calendar at year boundaries", () => {
  assert.equal(currentMonth(new Date("2025-12-31T16:00:00Z")),"2026-01");
  assert.equal(currentMonth(new Date("2025-12-31T15:59:59Z")),"2025-12");
});
test("overview opens in current month and supports historical years and independent months", async () => {
  const originalDashboard=api.getDashboard, originalTransactions=api.getDashboardTransactions;
  let r;
  try {
    const calls=[];
    api.getDashboard=async month=>{calls.push(month);return snapshot(month);};
    api.getDashboardTransactions=async()=>({transactions:[],total_count:0,offset:0,available_months:["2026-10","2025-08"],available_categories:[]});
    await act(async()=>{r=create(createElement(DashboardPage));});
    assert.equal(calls[0],currentMonth());
    assert.ok(r.root.findByProps({id:"dashboard-year"}).findAllByType("option").some(n=>n.props.value==="2025"));
    const nav=text(r.root.findByProps({"aria-label":"金融服务"}));
    assert.doesNotMatch(nav,/订阅总览|消费报告/);
    assert.match(nav,/预约与周期转账/);
    await act(async()=>r.root.findByProps({id:"dashboard-year"}).props.onChange({target:{value:"2025"}}));
    assert.equal(calls.at(-1),`2025-${currentMonth().slice(5)}`);
    await act(async()=>r.root.findByProps({id:"dashboard-month"}).props.onChange({target:{value:"08"}}));
    assert.equal(calls.at(-1),"2025-08");
    assert.match(text(r.toJSON()),/2025年8月消费总览/);
  } finally {
    if(r)await act(async()=>r.unmount());
    api.getDashboard=originalDashboard;api.getDashboardTransactions=originalTransactions;
  }
});
