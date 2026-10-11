import type { components } from "@banking/api-client";

type Result = components["schemas"]["WealthReadResult"];

/** Present saved facts, including legacy replies, without replaying model/tool prose. */
export function wealthAnswer(outputs: Record<string, unknown>[]): Result | null {
  const results = outputs.flatMap(output => {
    const saved = (output.wealth_results ?? []) as Result[];
    const index = output.wealth_final_result_index;
    return typeof index === "number" && saved[index] ? [saved[index]] : saved;
  });
  if (!results.length) return null;
  // New outputs carry an explicit final analysis. Legacy outputs keep only the last
  // saved result; absent historical reasoning is never reconstructed from field presence.
  const final = results.at(-1)!;
  return {...final, products:final.products ?? [], selected_reasons: {}, reasons:(final.reasons ?? []).map(wealthReason)};
}

export function wealthReason(reason: string): string {
  if (reason.includes("确定性筛选")) return "已根据你的风险测评和本次需求筛选。产品不保证本金或收益。";
  if (reason.includes("已按风险偏好")) return "当时按已有条件筛选；未保存的预算和用款安排仍需确认。";
  return reason.replace(/Mock测评/g, "模拟风险测评");
}

export function isWealthOnlyAnswer(outputs: Record<string, unknown>[]): boolean {
  return outputs.length > 0 && outputs.every(output => (Array.isArray(output.wealth_results) || Boolean(output.wealth_analysis))
    && !["account_results", "payee_results", "analysis_snapshot", "financial_display", "subscription_analysis_snapshot", "report_id", "aa_request_id", "transaction_anomaly_snapshot"].some(key => output[key]));
}
