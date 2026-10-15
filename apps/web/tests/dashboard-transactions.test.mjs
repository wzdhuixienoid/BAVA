import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import "./tsx-loader.mjs";
const { api } = await import("../lib/api/client.ts");
const { RecentTransactions } = await import("../features/dashboard/RecentTransactions.tsx");
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const row = (id, merchant = id) => ({transaction_id:id, merchant, description:"消费", category:"FOOD", occurred_at:"2026-08-01T00:00:00Z", amount_display:"¥12.34", currency:"CNY", account_id:"a"});
const page = (transactions, total_count = transactions.length) => ({transactions, total_count, offset:0, available_months:["2026-10","2026-08","2025-06"], available_categories:["FOOD","TRAVEL"]});
const text = n => typeof n === "string" ? n : (n?.children ?? []).map(text).join("");
const button = (r, name) => r.root.findAllByType("button").find(n => text(n) === name);
const choose = async (r, label, value) => act(async () => r.root.findByProps({"aria-label":label}).props.onChange({target:{value}}));
const deferred = () => {let resolve;return {promise:new Promise(r=>{resolve=r;}),resolve};};
async function render(fn) {
  const original = api.getDashboardTransactions;
  let r;
  try {await fn(async () => {await act(async () => {r = create(createElement(RecentTransactions, {transactions:[], accountNames:{a:"工资卡",b:"旅行卡"}}));});return r;});}
  finally {if(r)await act(async()=>r.unmount());api.getDashboardTransactions=original;}
}

test("month, category and account filters combine, retain all options, and can be cleared", async () => render(async mount => {
  const calls=[];
  api.getDashboardTransactions=async filters=>{calls.push(filters);return filters.account_id ? page([]) : page([row("one")]);};
  const r=await mount();
  await choose(r,"筛选账单年份","2025");
  assert.deepEqual(calls.at(-1),{year:"2025",month_number:"",category:"",account_id:""});
  await choose(r,"筛选账单月份","6");
  await choose(r,"筛选账单类别","TRAVEL");
  await choose(r,"筛选账单账户","b");
  assert.deepEqual(calls.at(-1),{year:"2025",month_number:"6",category:"TRAVEL",account_id:"b"});
  assert.match(text(r.toJSON()),/没有符合筛选条件/);
  assert.equal(r.root.findByProps({"aria-label":"筛选账单年份"}).findAllByType("option").length,3);
  assert.equal(r.root.findByProps({"aria-label":"筛选账单月份"}).findAllByType("option").length,13);
  await act(async()=>button(r,"清除筛选").props.onClick());
  assert.deepEqual(calls.at(-1),{year:"",month_number:"",category:"",account_id:""});
  assert.match(text(r.root.findByType("tbody")),/one/);
  assert.equal(button(r,"清除筛选"),undefined);
  await choose(r,"筛选账单月份","8");
  assert.deepEqual(calls.at(-1),{year:"",month_number:"8",category:"",account_id:""});
}));

test("late responses cannot overwrite newer filter results", async () => render(async mount => {
  const old=deferred();
  api.getDashboardTransactions=filters=>filters.year==="2025" ? old.promise : Promise.resolve(page([row(`${filters.year || "all"}-new`)]));
  const r=await mount();
  await choose(r,"筛选账单年份","2025");
  await choose(r,"筛选账单年份","2026");
  await act(async()=>old.resolve(page([row("stale")])));
  assert.match(text(r.root.findByType("tbody")),/2026-new/);
  assert.doesNotMatch(text(r.root.findByType("tbody")),/stale/);
}));

test("load more preserves filters, deduplicates clicks, and discards pages after filters change", async () => render(async mount => {
  const pending=deferred();let moreCalls=[];
  api.getDashboardTransactions=filters=>{
    if(filters.offset){moreCalls.push(filters);return pending.promise;}
    return Promise.resolve(filters.category ? page([row("filtered")]) : page([row("first"),row("second")],3));
  };
  const r=await mount();
  await act(async()=>{button(r,"加载更多账单").props.onClick();button(r,"加载更多账单").props.onClick();});
  assert.equal(moreCalls.length,1);assert.equal(moreCalls[0].offset,2);
  await choose(r,"筛选账单类别","TRAVEL");
  await act(async()=>pending.resolve(page([row("stale-page")],3)));
  assert.match(text(r.root.findByType("tbody")),/filtered/);
  assert.doesNotMatch(text(r.root.findByType("tbody")),/first|stale-page/);
}));

test("query failures offer retry and keep filter controls available", async () => render(async mount => {
  let calls=0;
  api.getDashboardTransactions=async()=>{if(++calls===1)throw Error("网络失败");return page([row("recovered")]);};
  const r=await mount();
  assert.match(text(r.toJSON()),/网络失败/);
  assert.equal(r.root.findAllByType("select").length,4);
  await act(async()=>button(r,"重试").props.onClick());
  assert.match(text(r.root.findByType("tbody")),/recovered/);
}));

test("successful pagination appends transactions in order with the selected month", async () => render(async mount => {
  const calls=[];
  api.getDashboardTransactions=async filters=>{
    calls.push(filters);
    return filters.offset ? page([row("third")],3) : page([row("first"),row("second")],3);
  };
  const r=await mount();
  await choose(r,"筛选账单年份","2026");
  await choose(r,"筛选账单月份","8");
  await act(async()=>button(r,"加载更多账单").props.onClick());
  assert.deepEqual(calls.at(-1),{year:"2026",month_number:"8",category:"",account_id:"",offset:2});
  const rows=r.root.findByType("tbody").findAllByType("tr");
  assert.equal(rows.length,3);
  assert.match(text(rows[0]),/first/);assert.match(text(rows[1]),/second/);assert.match(text(rows[2]),/third/);
  assert.equal(button(r,"加载更多账单"),undefined);
}));

test("statement labels, cash directions and refresh show newly posted business entries", async () => render(async mount => {
  let calls=0;
  api.getDashboardTransactions=async()=>page(++calls===1 ? [
    {...row("purchase","演示稳享日日"), category:"WEALTH", direction:"DEBIT", source:"WEALTH", amount_display:"-¥600.00", description:"理财申购 · 已入账"},
    {...row("credit","转账收入"), category:"TRANSFER", direction:"CREDIT", source:"TRANSFER", amount_display:"+¥28.00"},
  ] : [{...row("renewal","海浪音乐"), category:"SUBSCRIPTION", direction:"DEBIT", source:"SUBSCRIPTION", amount_display:"-¥15.00", description:"订阅续费 · 已入账"}]);
  const r=await mount();
  assert.match(text(r.root.findByProps({"aria-label":"账单明细"})),/账单明细.*已入账收支/);
  const body=r.root.findByType("tbody");
  assert.match(text(body),/理财.*-¥600.00.*转账收入.*转账.*\+¥28.00/);
  assert.ok(body.findAllByType("td").some(n=>n.props.className.includes("text-emerald-700")));
  await act(async()=>button(r,"刷新账单").props.onClick());
  assert.equal(calls,2);
  assert.match(text(r.root.findByType("tbody")),/海浪音乐.*订阅续费 · 已入账.*-¥15.00/);
}));
