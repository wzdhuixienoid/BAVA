import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { renderToStaticMarkup } from "react-dom/server";
import "./tsx-loader.mjs";

const { WorkspaceNavigation } = await import("../features/navigation/WorkspaceNavigation.tsx");
const { default: TransfersPage } = await import("../app/transfers/page.tsx");
const { ConversationPanel } = await import("../features/conversation/ConversationPanel.tsx");
const { api } = await import("../lib/api/client.ts");
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.self = globalThis;
const text = node => typeof node === "string" ? node : (node?.children ?? []).map(text).join("");

test("workspace offers one transfer hub and consistently styled services in the requested order", async () => {
  let renderer;
  try {
    await act(async () => { renderer = create(createElement(WorkspaceNavigation)); });
    const links = renderer.root.findAllByType("a");
    assert.deepEqual(links.map(node => [text(node), node.props.href]), [
      ["金融总览 Dashboard", "/dashboard"], ["转账与收款", "/transfers"],
      ["订阅管理", "/subscriptions"], ["理财中心", "/wealth"], ["历史消费报告", "/reports"],
    ]);
    assert.equal(new Set(links.slice(1).map(node => node.props.className)).size, 1);
    const html = renderToStaticMarkup(createElement(TransfersPage));
    for (const href of ["/scheduled-transfers", "/aa", "/payees"]) assert.match(html, new RegExp(`href="${href}"`));
    assert.match(html, /返回工作台/);
  } finally {
    if (renderer) await act(async () => renderer.unmount());
  }
});

test("conversation loads and sends in the full workspace without the removed event index or its AA request", async () => {
  const original = Object.fromEntries(["getConversation", "listTasks", "listReports", "listWorkflows", "getSecurityStatus", "listPlans", "listAA", "postMessage"].map(key => [key, api[key]]));
  const originalFetch = globalThis.fetch, originalWindow = globalThis.window, originalStorage = globalThis.localStorage;
  let renderer, aaCalls = 0;
  const sent = [];
  const messages = [{ message_id: "a1", role: "ASSISTANT", content: "已入账转账合计550元。" }];
  try {
    globalThis.window = { location: { href: "http://localhost:3000/" }, history: {} };
    globalThis.localStorage = { getItem: () => null };
    globalThis.fetch = (_url, { signal }) => new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
    });
    api.getConversation = async () => ({ conversation_id: "c", title: "转账分析", messages: [...messages] });
    api.listTasks = api.listReports = api.listWorkflows = api.listPlans = async () => [];
    api.getSecurityStatus = async () => ({ write_locked: false });
    api.listAA = async () => { aaCalls++; throw new Error("removed index should not load AA"); };
    api.postMessage = async (id, content) => {
      sent.push([id, content]);
      messages.push({ message_id: "u2", role: "USER", content });
    };
    await act(async () => { renderer = create(createElement(ConversationPanel, { conversationId: "c" })); });
    const content = text(renderer.toJSON());
    assert.match(content, /转账分析/);
    assert.match(content, /已入账转账合计550元/);
    assert.doesNotMatch(content, /已完成事件|完成事件可快速查找/);
    assert.equal(renderer.root.findAllByType("aside").length, 0);
    const workspace = renderer.root.findByProps({ "aria-label": "对话工作区" });
    assert.match(workspace.props.className, /flex-1/);
    assert.equal(workspace.findAllByType("form").length, 1);
    await act(async () => renderer.root.findByProps({ "aria-label": "消息" }).props.onChange({ target: { value: "下一页" } }));
    await act(async () => renderer.root.findByType("form").props.onSubmit({ preventDefault() {} }));
    assert.deepEqual(sent, [["c", "下一页"]]);
    assert.match(text(renderer.toJSON()), /下一页/);
    assert.equal(aaCalls, 0);
  } finally {
    if (renderer) await act(async () => renderer.unmount());
    Object.assign(api, original);
    globalThis.fetch = originalFetch;
    globalThis.window = originalWindow;
    globalThis.localStorage = originalStorage;
  }
});
