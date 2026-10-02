import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { accountResults } from "../features/accounts/presentation.ts";

import "./tsx-loader.mjs";
const { AccountResults } = await import("../features/accounts/AccountResults.tsx");
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
});

test("real assistant turn keeps authoritative balance card visible with false LLM prose", () => {
  const turn = {
    id: "t1", replies: [{ message_id: "m1", role: "ASSISTANT", content: "你的余额是 1 元。" }],
    tasks: [{ task_id: "t1", status: "COMPLETED", input: {}, output: { account_results: [balance] } }],
    plans: [], workflows: [], reports: [],
  };
  const html = renderToStaticMarkup(createElement(AssistantTurn, {
    turn, activityRevision: 0, highlightedResult: null, onRefresh: async () => {},
  }));
  assert.match(html, /你的余额是 1 元。/);
  assert.match(html, /aria-label="工资卡余额"/);
  assert.match(html, /¥23,864\.52/);
  assert.equal((html.match(/¥23,864\.52/g) ?? []).length, 1);
  assert.deepEqual(accountResults([{ answer: "余额是1元" }]), []);
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
