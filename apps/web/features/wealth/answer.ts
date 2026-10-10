import type { components } from "@banking/api-client";

type Result = components["schemas"]["WealthReadResult"];

/** Present saved facts, including legacy replies, without replaying model/tool prose. */
export function wealthAnswer(outputs: Record<string, unknown>[]): Result | null {
  const results = outputs.flatMap(output => (output.wealth_results ?? []) as Result[]);
  if (!results.length) return null;
  // A recommendation is the final selection, not the preceding catalogue lookup.
  const recommendations = results.filter(result => result.constraints || Object.keys(result.selected_reasons ?? {}).length);
  const productResults = recommendations.length ? recommendations.slice(-1) : results;
  const unique = <T,>(rows: T[], key: (row: T) => string) => [...new Map(rows.map(row => [key(row), row])).values()];
  return {
    ...productResults.at(-1),
    excluded: productResults.at(-1)?.excluded ?? {},
    products: unique(productResults.flatMap(result => result.products ?? []), product => product.product_id),
    selected_reasons: Object.assign({}, ...productResults.map(result => result.selected_reasons ?? {})),
    reasons: [...new Set(productResults.flatMap(result => result.reasons ?? []).map(wealthReason))],
    evidence: unique(results.flatMap(result => result.evidence ?? []), row => row.document_id),
    positions: unique(results.flatMap(result => result.positions ?? []), row => row.position_id),
    orders: unique(results.flatMap(result => result.orders ?? []), row => row.order_id),
  };
}

export function wealthReason(reason: string): string {
  if (reason.includes("确定性筛选")) return "已根据你的风险测评和本次需求筛选。产品不保证本金或收益。";
  if (reason.includes("已按风险偏好")) return "符合你的用款时间和起购金额要求。";
  return reason.replace(/Mock测评/g, "模拟风险测评");
}

export function isWealthOnlyAnswer(outputs: Record<string, unknown>[]): boolean {
  return outputs.length > 0 && outputs.every(output => Array.isArray(output.wealth_results)
    && !["account_results", "payee_results", "analysis_snapshot", "financial_display", "subscription_analysis_snapshot", "report_id", "aa_request_id", "transaction_anomaly_snapshot"].some(key => output[key]));
}
