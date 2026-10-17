import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { accountResults } from "../features/accounts/presentation.ts";
import { queryTime } from "../lib/presentation/time.ts";

import "./tsx-loader.mjs";
const { AccountResults } = await import("../features/accounts/AccountResults.tsx");
const { AccountAnswer } = await import("../features/accounts/AccountAnswer.tsx");
const { AssistantTurn } = await import("../features/conversation/AssistantTurn.tsx");

const balance = {
  kind: "ACCOUNT_BALANCE", account_id: "acc_salary", display_name: "工资卡",
  masked_number: "****6688", account_type: "DEBIT", currency: "CNY", balance: "23864.52",
  balance_display: "¥23,864.52", as_of: "2026-10-02T08:00:00Z",
};

test("balance card renders backend display field without recalculating the raw decimal", () => {
  const html = renderToStaticMarkup(createElement(AccountResults, {
    results: [{ ...balance, balance: "9007199254740993.01", balance_display: "¥9,007,199,254,740,993.01" }],
  }));
  assert.match(html, /¥9,007,199,254,740,993\.01/);
  assert.match(html, /工资卡/);
  assert.match(html, /\*\*\*\*6688/);
  assert.match(html, /2026-10-02T08:00:00Z/);
  assert.match(html, /2026-10-02 16:00:00/);
});

test("assistant gives one grounded answer without cards or duplicate LLM prose", () => {
  const turn = {
    id: "t1", replies: [{ message_id: "m1", role: "ASSISTANT", content: "你的余额是 1 元。" }],
    tasks: [{ task_id: "t1", status: "COMPLETED", input: {}, output: { account_results: [balance] } }],
    plans: [], workflows: [], reports: [],
  };
  const html = renderToStaticMarkup(createElement(AssistantTurn, {
    turn, activityRevision: 0, onRefresh: async () => {},
  }));
  assert.doesNotMatch(html, /你的余额是 1 元。|助理说明|账户查询结果|<section/);
  assert.match(html, /aria-label="账户查询回复"/);
  assert.match(html, /¥23,864\.52/);
  assert.equal((html.match(/¥23,864\.52/g) ?? []).length, 1);
  assert.deepEqual(accountResults([{ answer: "余额是1元" }]), []);
});

test("account answer merges the list and balances and explains debt without inventing a total", () => {
  const html = renderToStaticMarkup(createElement(AccountAnswer, { results: [
    { kind: "ACCOUNT_LIST", as_of: balance.as_of, accounts: [
      { ...balance, status: "ACTIVE" },
      { ...balance, account_id: "credit", display_name: "信用卡", masked_number: "****9527", status: "ACTIVE" },
    ] },
    balance,
    { ...balance, account_id: "credit", display_name: "信用卡", masked_number: "****9527",
      account_type: "CREDIT", balance: "-4860.35", balance_display: "-¥4,860.35" },
  ] }));
  assert.equal((html.match(/工资卡/g) ?? []).length, 1);
  assert.match(html, /信用卡负余额表示欠款/);
  assert.match(html, /-¥4,860\.35/);
  assert.doesNotMatch(html, /合计|总计|卡片|<section/);
  assert.equal((html.match(/查询时间/g) ?? []).length, 1);
  assert.match(html, /2026-10-02 16:00:00/);
});

test("query timestamps show seconds in Beijing time, including date rollover", () => {
  assert.equal(queryTime("2026-10-08T05:13:51.215913Z"), "2026-10-08 13:13:51");
  assert.equal(queryTime("2026-10-08T18:13:51Z"), "2026-10-09 02:13:51");
  assert.equal(queryTime("invalid"), "—");
});

test("account list uses typed structured identity and includes no inferred balance", () => {
  const html = renderToStaticMarkup(createElement(AccountResults, { results: [{
    kind: "ACCOUNT_LIST", as_of: balance.as_of, accounts: [{
      account_id: "acc_salary", display_name: "工资卡", masked_number: "****6688",
      account_type: "DEBIT", currency: "CNY", status: "ACTIVE",
    }],
  }] }));
  assert.match(html, /工资卡/);
  assert.match(html, /\*\*\*\*6688/);
  assert.doesNotMatch(html, /¥/);
});

test("combined banking answer keeps the typed balance and consumption explanation visible", () => {
  const turn = {
    id: "combined", user: { content: "查余额并分析八月消费" },
    replies: [{ message_id: "m", role: "ASSISTANT", content: "八月消费主要集中在住房和购物。" }],
    tasks: [{ task_id: "t", status: "COMPLETED", output: {
      agent_id: "agent:personal-banking", account_results: [balance],
      analysis_snapshot: { spending_summary: { period: "2026-08", total_spending: "16547.30" } },
    } }], plans: [], workflows: [], reports: [],
  };
  const html = renderToStaticMarkup(createElement(AssistantTurn, {
    turn, activityRevision: 0, onRefresh: async () => {},
  }));
  assert.match(html, /¥23,864\.52/);
  assert.match(html, /八月消费主要集中在住房和购物/);
  assert.equal((html.match(/aria-label="账户查询回复"/g) ?? []).length, 1);
});

test("combined balance and anomaly result preserves both facts while replacing duplicate prose", () => {
  const turn = {
    id: "combined-anomaly", user: { content: "查余额并检查异常交易" },
    replies: [{ message_id: "m", role: "ASSISTANT", content: "这段旧的重复文字不应出现。" }],
    tasks: [{ task_id: "t", status: "COMPLETED", output: {
      agent_id: "agent:personal-banking", account_results: [balance],
      analysis_snapshot: { period: null },
      transaction_anomaly_answer: "在指定区间发现值得核对的交易。",
    } }], plans: [], workflows: [], reports: [],
  };
  const html = renderToStaticMarkup(createElement(AssistantTurn, {
    turn, activityRevision: 0, onRefresh: async () => {},
  }));
  assert.match(html, /¥23,864\.52/);
  assert.match(html, /发现值得核对的交易/);
  assert.doesNotMatch(html, /这段旧的重复文字/);
});

const statement = {
  as_of: "2026-10-15T12:00:00Z", start_at: "2026-09-15T12:00:00Z", end_at: "2026-10-15T12:00:00Z",
  total_count: 12, offset: 0, next_offset: 10,
  posting_scope: "仅包含已实际入账流水；待处理和失败不等于已入账。",
  transactions: [{
    transaction_id: "transfer:internal-id:debit", merchant: "李小雨", description: "餐费",
    category: "TRANSFER", category_display: "转账", amount: "123.45", amount_display: "-¥123.45",
    occurred_at: "2026-10-14T12:00:00Z", occurred_at_display: "2026年10月14日 20:00",
    account_id: "acc_salary", account_display: "工资卡 · ****6688", currency: "CNY", direction: "DEBIT", source: "TRANSFER", status: "POSTED",
  }],
};

test("statement with account lookup shows bank rows and pagination instead of false model refusal", () => {
  const turn = {
    id: "statement", user: { content: "查询工资卡转账记录" },
    replies: [{ message_id: "m", role: "ASSISTANT", content: "我没有任何工具能查转账历史。" }],
    tasks: [{ task_id: "t", status: "COMPLETED", output: {
      account_results: [{ kind: "ACCOUNT_LIST", as_of: balance.as_of, accounts: [balance] }],
      statement_results: [statement],
    } }], plans: [], workflows: [], reports: [],
  };
  const html = renderToStaticMarkup(createElement(AssistantTurn, { turn, activityRevision: 0, onRefresh: async () => {} }));
  assert.match(html, /账单查询回复|李小雨|-¥123\.45|输入“下一页”/);
  assert.match(html, /2026年10月14日 20:00/);
  assert.doesNotMatch(html, /没有任何工具|transfer:internal-id|账户查询回复/);
  assert.equal((html.match(/-¥123\.45/g) ?? []).length, 1);
});

test("combined statement and balance never hides either typed result", () => {
  const turn = {
    id: "statement-balance", replies: [{ message_id: "m", role: "ASSISTANT", content: "重复模型回复" }],
    tasks: [{ task_id: "t", status: "COMPLETED", output: { account_results: [balance], statement_results: [statement] } }],
    plans: [], workflows: [], reports: [],
  };
  const html = renderToStaticMarkup(createElement(AssistantTurn, { turn, activityRevision: 0, onRefresh: async () => {} }));
  assert.match(html, /账单查询回复/);
  assert.match(html, /账户查询回复/);
  assert.match(html, /¥23,864\.52/);
  assert.match(html, /-¥123\.45/);
  assert.doesNotMatch(html, /重复模型回复/);
});

test("empty statement explains posted scope without inventing transactions", () => {
  const turn = {
    id: "empty", replies: [], tasks: [{ task_id: "t", status: "COMPLETED", output: {
      statement_results: [{ ...statement, transactions: [], total_count: 0, next_offset: null }],
    } }], plans: [], workflows: [], reports: [],
  };
  const html = renderToStaticMarkup(createElement(AssistantTurn, { turn, activityRevision: 0, onRefresh: async () => {} }));
  assert.match(html, /没有已入账记录/);
  assert.match(html, /待处理和失败不等于已入账/);
  assert.doesNotMatch(html, /李小雨|下一页|123\.45/);
});

const transferAnalysis = {
  ...statement, total_count: 6, next_offset: 1,
  transactions: [{ ...statement.transactions[0], merchant: "张三", amount: "10.00", amount_display: "-¥10.00" }],
  summary: {
    is_transfer: true, scope_display: "全部账户 · 转账", totals: [{ currency: "CNY", debit_count: 6, credit_count: 0, total_debit: "60.00", total_credit: "0", debit_display: "¥60.00", credit_display: "¥0.00" }],
    counterparties: [], counterparty_group_count: 2, latest_transaction: null, insights: [], grouping_note: null,
  },
  answer: `**分析区间：2026年09月15日 20:00 至 2026年10月15日 20:00（北京时间，终点不含）**

## 转账总览

| 币种 | 转出金额 / 笔数 | 转入金额 / 笔数 |
| --- | ---: | ---: |
| 人民币 | ¥60.00 / 6笔 | ¥0.00 / 0笔 |

## 按收款人／付款方汇总

| 收款人／付款方 | 方向 | 金额 | 笔数 | 占比 |
| --- | --- | ---: | ---: | ---: |
| 张三 | 转出 | ¥50.00 | 5 | 83.3% |
| 王五 | 转出 | ¥10.00 | 1 | 16.7% |

## 解读

- 转出主要集中在张三，共5笔、¥50.00。
- 所查范围内最近一笔发生在2026年10月14日 20:00，张三，转出¥10.00。

## 最近转账明细

| 时间 | 对手方 | 金额 |
| --- | --- | ---: |
| 2026年10月14日 20:00 | 张三 | -¥10.00 |

当前展示第1条，共6条。输入“下一页”可继续查看；上方汇总不受分页影响。`,
};

test("transfer reply renders period totals recipient groups insights and recent detail as one analysis", () => {
  const turn = {
    id: "analysis", replies: [{ message_id: "m", role: "ASSISTANT", content: "错误的模型总额999元" }],
    tasks: [{ task_id: "t", status: "COMPLETED", output: { statement_results: [transferAnalysis] } }],
    plans: [], workflows: [], reports: [],
  };
  const html = renderToStaticMarkup(createElement(AssistantTurn, { turn, activityRevision: 0, onRefresh: async () => {} }));
  assert.match(html, /<h2>转账总览<\/h2>/);
  assert.match(html, /<h2>按收款人／付款方汇总<\/h2>/);
  assert.match(html, /<h2>解读<\/h2>/);
  assert.match(html, /最近转账明细/);
  assert.match(html, /¥60\.00|¥50\.00|83\.3%|王五|最近一笔/);
  assert.equal((html.match(/<table>/g) ?? []).length, 3);
  assert.doesNotMatch(html, /999元|transfer:internal-id/);
});

test("partial historical rows never invent a total or pretend to be a full analysis", () => {
  const turn = {
    id: "legacy", replies: [], tasks: [{ task_id: "t", status: "COMPLETED", output: { statement_results: [statement] } }],
    plans: [], workflows: [], reports: [],
  };
  const html = renderToStaticMarkup(createElement(AssistantTurn, { turn, activityRevision: 0, onRefresh: async () => {} }));
  assert.match(html, /历史结果只有部分明细/);
  assert.doesNotMatch(html, /<h2>转账总览|¥1,481\.40/);
});
