import assert from "node:assert/strict";
import test from "node:test";
import {createElement} from "react";
import {act, create} from "react-test-renderer";
import {renderToStaticMarkup} from "react-dom/server";
import "./tsx-loader.mjs";
const {TransferLimitSettings} = await import("../features/security/TransferLimitSettings.tsx");
const {SubscriptionQueryConsent} = await import("../features/security/SubscriptionQueryConsent.tsx");
const {AssistantTurn} = await import("../features/conversation/AssistantTurn.tsx");
const {ReauthenticationForm} = await import("../features/workflows/ReauthenticationForm.tsx");
const {api} = await import("../lib/api/client.ts");
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.self = globalThis;
const text = node => typeof node === "string" ? node : (node?.children ?? []).map(text).join("");

test("limit changes require review and verification, retain server version, and clear code", async () => {
  const old = {transferPreference: api.transferPreference, saveTransferPreference: api.saveTransferPreference};
  let view, calls = [], refresh = 0;
  try {
    api.transferPreference = async () => ({passwordless_limit: "200.00", passwordless_limit_display: "¥200.00", version: 7});
    api.saveTransferPreference = async (...args) => { calls.push(args); return {passwordless_limit: args[0], passwordless_limit_display: "¥50.00", version: 8}; };
    await act(async () => { view = create(createElement(TransferLimitSettings, {onSaved: async () => { refresh++; }})); });
    const input = view.root.findByProps({"aria-label": "新免密额度"});
    await act(async () => input.props.onChange({target: {value: "200.01"}}));
    assert.equal(view.root.findByType("button").props.disabled, true);
    await act(async () => input.props.onChange({target: {value: "50"}}));
    await act(async () => view.root.findByType("button").props.onClick());
    assert.equal(calls.length, 0);
    assert.match(text(view.toJSON()), /50 元/);
    assert.doesNotMatch(text(view.toJSON()), /135790|246810|本地演示|无需安装/);
    assert.equal(view.root.findAllByType("button")[0].props.disabled, true);
    await act(async () => view.root.findByProps({"aria-label": "额度设置验证码"}).props.onChange({target: {value: "123456"}}));
    await act(async () => view.root.findAllByType("button")[0].props.onClick());
    assert.deepEqual(calls, [["50", 7, "123456"]]);
    assert.equal(refresh, 1);
    assert.equal(view.root.findAllByProps({"aria-label": "额度设置验证码"}).length, 0);
    assert.match(text(view.toJSON()), /¥50.00/);
  } finally { if (view) await act(async () => view.unmount()); Object.assign(api, old); }
});

test("subscription read waits for a click and never retries original request when consent fails", async () => {
  const old = {confirmSubscriptionRead: api.confirmSubscriptionRead, postMessage: api.postMessage};
  let view, calls = [];
  try {
    api.confirmSubscriptionRead = async () => { calls.push("confirm"); throw new Error("授权失败"); };
    api.postMessage = async (...args) => calls.push(args);
    await act(async () => { view = create(createElement(SubscriptionQueryConsent, {conversationId: "owner-conversation", content: "我有哪些订阅", onRefresh: async () => {}})); });
    assert.deepEqual(calls, []);
    await act(async () => view.root.findByType("button").props.onClick());
    assert.deepEqual(calls, ["confirm"]);
    assert.match(text(view.toJSON()), /授权失败/);
    api.confirmSubscriptionRead = async () => { calls.push("confirmed"); };
    await act(async () => view.root.findByType("button").props.onClick());
    assert.deepEqual(calls, ["confirm", "confirmed", ["owner-conversation", "我有哪些订阅"]]);
    assert.equal(view.root.findByType("button").props.disabled, true);
  } finally { if (view) await act(async () => view.unmount()); Object.assign(api, old); }
});

test("bank answer with no successful evidence suppresses invented balance and transaction success", () => {
  const turn = {id: "t", user: {content: "查余额"}, replies: [{message_id: "m", role: "ASSISTANT", content: "余额999999元，转账已成功到账"}], tasks: [{task_id: "t", status: "COMPLETED", input: {}, output: {agent_id: "agent:personal-banking"}}], plans: [], workflows: [], reports: []};
  const html = renderToStaticMarkup(createElement(AssistantTurn, {turn, activityRevision: 0, onRefresh: async () => {}}));
  assert.doesNotMatch(html, /999999|已成功到账/);
  assert.match(html, /无法确认/);
});


test("red workflow keeps the identity code private and submits only on click", async () => {
  const old = {verifyTransferReauthentication: api.verifyTransferReauthentication};
  let view, calls = [];
  try {
    api.verifyTransferReauthentication = async (...args) => { calls.push(args); };
    await act(async () => { view = create(createElement(ReauthenticationForm, {workflow: {workflow_id: "w", version: 3, reauth_summary: {method: "MOCK_CODE", status: "PENDING", reauth_id: "r"}}, busy: false, act: async action => action()})); });
    assert.doesNotMatch(text(view.toJSON()), /135790|246810/);
    assert.doesNotMatch(text(view.toJSON()), /管理认证器/);
    assert.deepEqual(calls, []);
    await act(async () => view.root.findByType("input").props.onChange({target: {value: "135790"}}));
    await act(async () => view.root.findByType("button").props.onClick());
    assert.deepEqual(calls, [["w", "r", "135790", 3]]);
    assert.equal(view.root.findByType("input").props.value, "");
  } finally { if (view) await act(async () => view.unmount()); Object.assign(api, old); }
});
