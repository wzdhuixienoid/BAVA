import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import "./tsx-loader.mjs";
const { api } = await import("../lib/api/client.ts");
const { NotificationBell } = await import("../features/notifications/NotificationBell.tsx");
const { NotificationDetail } = await import("../features/notifications/NotificationDetail.tsx");
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.self = globalThis;
const text = n => typeof n === "string" ? n : (n?.children ?? []).map(text).join("");
const snapshot = { analysis_period_started_at: "2026-09-15T12:00:00Z", analysis_period_ended_at: "2026-10-15T12:00:00Z", insufficient_baseline: false, anomalies: [{ transaction_id: "txn", merchant_display: "测试商户", occurred_at: "2026-10-14T12:00:00Z", amount_display: "¥900.00", severity: "HIGH", currency: "CNY", anomaly_types: ["AMOUNT_SPIKE"], evidence_display: { AMOUNT_SPIKE: ["历史中位数：¥100.00", "金额倍数：9.00"] } }] };
const notice = { notification_id: "alert-1", kind: "TRANSACTION_ANOMALY", title: "交易异常提示 · 请核对", message: "工资卡 · ****6688 支出¥900.00，不代表已确认欺诈。", created_at: "2026-10-15T12:00:00Z", read_at: null, anomaly_snapshot: snapshot };

test("anomaly bell links to evidence, marks read, and removes deleted notifications", async () => {
  const original = { listNotifications: api.listNotifications, readNotification: api.readNotification, deleteNotification: api.deleteNotification };
  const originalWindow = globalThis.window, originalDocument = globalThis.document;
  let r, items = [notice], reads = 0;
  try {
    globalThis.window = { setInterval: () => 1, clearInterval() {}, addEventListener() {}, removeEventListener() {} };
    globalThis.document = { hidden: false, addEventListener() {}, removeEventListener() {} };
    api.listNotifications = async () => ({ items, unread_count: items.filter(n => !n.read_at).length, has_more: false });
    api.readNotification = async id => { assert.equal(id, "alert-1"); reads++; items = [{ ...notice, read_at: notice.created_at }]; };
    api.deleteNotification = async id => { assert.equal(id, "alert-1"); items = []; };
    await act(async () => { r = create(createElement(NotificationBell)); });
    assert.equal(r.root.findAllByProps({ "data-testid": "notification-unread-dot" }).length, 1);
    await act(async () => r.root.findByProps({ "aria-label": "消息提醒，1 条未读" }).props.onClick());
    const link = r.root.findAllByType("a").find(n => text(n) === "查看异常交易");
    assert.equal(link.props.href, "/notifications/alert-1");
    await act(async () => link.props.onClick({ defaultPrevented: true }));
    assert.equal(reads, 1);
    assert.equal(r.root.findAllByProps({ "data-testid": "notification-unread-dot" }).length, 0);
    await act(async () => r.root.findByProps({ "aria-label": "消息提醒" }).props.onClick());
    await act(async () => r.root.findByProps({ "aria-label": `删除消息：${notice.title}` }).props.onClick());
    assert.match(text(r.toJSON()), /暂无消息提醒/);
  } finally {
    if (r) await act(async () => r.unmount());
    Object.assign(api, original); globalThis.window = originalWindow; globalThis.document = originalDocument;
  }
});

test("notification detail presents the saved facts and rules without starting a new analysis", async () => {
  const original = api.getNotification;
  let r;
  try {
    api.getNotification = async id => { assert.equal(id, "alert-1"); return notice; };
    await act(async () => { r = create(createElement(NotificationDetail, { notificationId: "alert-1" })); });
    const content = text(r.toJSON());
    for (const expected of ["工资卡", "¥900.00", "金额倍数：9.00", "历史中位数", "提醒生成时", "不代表已确认欺诈"]) assert.ok(content.includes(expected), expected);
    assert.equal(r.root.findAllByType("form").length, 0);
  } finally {
    if (r) await act(async () => r.unmount());
    api.getNotification = original;
  }
});

test("inaccessible or deleted notification shows an error and never leaves another item's facts", async () => {
  const original = api.getNotification;
  let r;
  try {
    api.getNotification = async id => {
      if (id === "alert-1") return notice;
      throw new Error("未找到该消息");
    };
    await act(async () => { r = create(createElement(NotificationDetail, { notificationId: "alert-1" })); });
    await act(async () => r.update(createElement(NotificationDetail, { notificationId: "forbidden" })));
    assert.match(text(r.root.findByProps({ role: "alert" })), /未找到该消息/);
    assert.doesNotMatch(text(r.toJSON()), /测试商户|¥900.00/);
  } finally {
    if (r) await act(async () => r.unmount());
    api.getNotification = original;
  }
});
