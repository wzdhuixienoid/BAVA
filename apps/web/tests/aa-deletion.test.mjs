import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { renderToStaticMarkup } from "react-dom/server";
import "./tsx-loader.mjs";
const { AARequestCard } = await import("../features/aa/AARequestCard.tsx");
const { default: AAPage } = await import("../app/aa/page.tsx");
const { api } = await import("../lib/api/client.ts");
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.self = globalThis;
const text = n => typeof n === "string" ? n : (n?.children ?? []).map(text).join("");
const button = (r, label) => r.root.findAllByType("button").find(n => text(n) === label);
const cancelled = {
  request_id: "a", conversation_id: "c", created_at: "2026-10-15T00:00:00Z", version: 4,
  status: "CANCELLED", is_initiator: true, deadline: "2026-10-16T00:00:00Z", can_delete: true,
  snapshot: { total: "100.00", remark: "聚餐", deadline: "2026-10-16T00:00:00Z", collection_account: { display_name: "储蓄卡", masked_number: "****1024" }, participants: [] },
  receivable: "50.00", received: "0.00", outstanding: "50.00", self_paid: "50.00",
  shares: [{ share_id: "s", display_name: "张三", amount: "50.00", status: "CANCELLED", is_mine: false }, { share_id: "self", display_name: "我", amount: "50.00", status: "SELF_PAID", is_mine: true }],
};

test("AA page removes demo login, confirms list deletion and updates the empty state", async () => {
  const original = { listAA: api.listAA, getAA: api.getAA, aaAccounts: api.aaAccounts, deleteAA: api.deleteAA, mockSessions: api.mockSessions };
  let r, resolveDelete, demoCalls = 0;
  const calls = [];
  try {
    api.listAA = async () => [cancelled];
    api.getAA = async () => cancelled;
    api.aaAccounts = async () => [];
    api.mockSessions = async () => { demoCalls++; throw new Error("removed UI"); };
    api.deleteAA = (id, version) => { calls.push([id, version]); return new Promise(resolve => { resolveDelete = resolve; }); };
    await act(async () => { r = create(createElement(AAPage)); });
    assert.equal(demoCalls, 0);
    assert.doesNotMatch(text(r.toJSON()), /演示登录|部分收款|未收 ¥50|选择付款账户，再独立确认/);
    assert.match(text(r.toJSON()), /全部收款份额已取消/);
    await act(async () => button(r, "删除收款").props.onClick());
    assert.match(text(r.root.findByProps({ role: "dialog" })), /历史记录和审计会保留/);
    await act(async () => button(r, "保留收款").props.onClick());
    assert.equal(calls.length, 0);
    await act(async () => button(r, "删除收款").props.onClick());
    await act(async () => button(r, "确认删除").props.onClick());
    assert.deepEqual(calls, [["a", 4]]);
    assert.ok(button(r, "正在删除…").props.disabled);
    await act(async () => resolveDelete());
    assert.match(text(r.toJSON()), /当前身份没有 AA 请求/);
    assert.equal(button(r, "删除收款"), undefined);
  } finally {
    if (r) await act(async () => r.unmount());
    Object.assign(api, original);
  }
});

test("delete requires the server's eligibility and the initiator, and deleted chat records stay readable", () => {
  for (const overrides of [{ can_delete: false }, { is_initiator: false }, { can_delete: undefined, status: "PARTIAL_CLOSED" }]) {
    const html = renderToStaticMarkup(createElement(AARequestCard, { requestId: "a", initialRequest: { ...cancelled, ...overrides } }));
    assert.doesNotMatch(html, /删除收款/);
  }
  const html = renderToStaticMarkup(createElement(AARequestCard, { requestId: "a", initialRequest: { ...cancelled, deleted_from_list: true } }));
  assert.match(html, /已从列表删除，历史记录和审计保留/);
  assert.doesNotMatch(html, /删除收款|核对并付款/);
});

test("failed deletion preserves the request and refreshes eligibility instead of removing it", async () => {
  const original = { getAA: api.getAA, aaAccounts: api.aaAccounts, deleteAA: api.deleteAA };
  let r, current = cancelled, removed = false;
  try {
    api.getAA = async () => current;
    api.aaAccounts = async () => [];
    api.deleteAA = async () => {
      current = { ...cancelled, version: 5, can_delete: false };
      throw new Error("收款状态已变化，请核对最新状态后重试。");
    };
    await act(async () => { r = create(createElement(AARequestCard, { requestId: "a", initialRequest: cancelled, onDeleted: () => { removed = true; } })); });
    await act(async () => button(r, "删除收款").props.onClick());
    await act(async () => button(r, "确认删除").props.onClick());
    assert.equal(removed, false);
    assert.match(text(r.root.findByProps({ role: "alert" })), /状态已变化/);
    assert.match(text(r.toJSON()), /聚餐/);
    assert.equal(button(r, "删除收款"), undefined);
  } finally {
    if (r) await act(async () => r.unmount());
    Object.assign(api, original);
  }
});
