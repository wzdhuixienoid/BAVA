import assert from "node:assert/strict";
import test from "node:test";
import { subscriptionReport } from "../features/subscriptions/answer.ts";

test("subscription report explains missing charges and expired estimates without internal metadata", () => {
  const result = subscriptionReport({
    generated_at: "2026-10-09T00:00:00Z",
    subscriptions: [
      { merchant: "活力健身", management_type: "MANAGED", status: "ACTIVE", billing_interval: "MONTHLY", contract_amount_display: "¥128.00", last_charge_display: "¥0.00", last_charge_date: null, next_billing_at: "2026-11-07T00:00:00Z", next_billing_is_estimated: false, cancellable: true, evidence_count: 0 },
      { merchant: "晨光健身", management_type: "DETECTED_ONLY", status: "ACTIVE", billing_interval: "MONTHLY", last_charge_display: "¥109.00", last_charge_date: "2025-05-25", next_billing_at: "2025-06-24T00:00:00Z", next_billing_is_estimated: true, cancellable: false, evidence_count: 2 },
    ],
    monthly_cost_by_currency: [{ currency: "CNY", amount_display: "¥237.00" }],
    annual_projected_cost_by_currency: [], price_changes: [], upcoming_renewals: [],
  });
  assert.match(result, /¥128\.00/);
  assert.match(result, /暂无扣费记录/);
  assert.match(result, /待确认/);
  assert.match(result, /前往对应商户/);
  assert.doesNotMatch(result, /MANAGED|DETECTED_ONLY|cancellable|CNY|证据|快照|工具|Workflow|¥0\.00|2025-06-24/);
});
