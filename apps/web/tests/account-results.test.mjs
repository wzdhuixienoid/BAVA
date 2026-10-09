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
    turn, activityRevision: 0, highlightedResult: null, onRefresh: async () => {},
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
