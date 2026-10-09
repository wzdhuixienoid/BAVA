import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import "./tsx-loader.mjs";
const { default: PayeesPage } = await import("../app/payees/page.tsx");

test("payee form requests the full account and omits the removed explanatory text", () => {
  const html = renderToStaticMarkup(createElement(PayeesPage));
  assert.match(html, /收款账号/);
  assert.match(html, /请输入完整收款账号/);
  assert.match(html, /pattern="\[0-9\]\{12,32\}"/);
  assert.doesNotMatch(html, /账户尾号（模拟）|使用模拟账户资料。保存需要核对确认/);
  assert.match(html, /可转账收款人/);
  assert.doesNotMatch(html, /手机号|查找并锁定/);
});

