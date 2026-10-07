import assert from "node:assert/strict";
import test from "node:test";
import { consumeSubscriptionPrefill } from "../features/conversation/subscription-prefill.ts";

test("subscription prefill is consumed once across conversation remounts", () => {
  let href = "http://localhost:3000/?resume=活力健身&conversation=c1#latest";
  const state = { existing: "next-router-state" };
  const history = { state, replaceState(next, _title, path) {
    assert.equal(next, state); href = new URL(path, href).href;
  } };
  assert.equal(consumeSubscriptionPrefill(href, history), "恢复活力健身订阅");
  assert.equal(href, "http://localhost:3000/?conversation=c1#latest");
  assert.equal(consumeSubscriptionPrefill(href, history), null);
});

test("cancel is consumed, while a new explicit subscription navigation prefills again", () => {
  const history = { state: null, replaceState() {} };
  assert.equal(consumeSubscriptionPrefill("http://localhost:3000/?cancel=星幕视频", history), "取消星幕视频");
  assert.equal(consumeSubscriptionPrefill("http://localhost:3000/?resume=海浪音乐", history), "恢复海浪音乐订阅");
});

test("no intent leaves URL and current composer draft untouched", () => {
  assert.equal(consumeSubscriptionPrefill("http://localhost:3000/?conversation=c2", {
    state: null, replaceState() { assert.fail("URL should not change"); },
  }), null);
});
