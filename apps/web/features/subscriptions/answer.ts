import type { components } from "@banking/api-client";

type Snapshot = components["schemas"]["SubscriptionAnalysisSnapshot"];
type Item = components["schemas"]["SubscriptionItem"];

const date = (value: string | null | undefined) => value ? value.slice(0, 10) : "待确认";
const cell = (value: string) => value.replace(/\|/g, "\\|").replace(/\n/g, " ");

// Render saved reports from their original data, without exposing internal fields.
export function subscriptionReport(snapshot: Snapshot): string {
  const lines = ["以下是你的订阅情况："];
  const groups: [string, Item[]][] = [
    ["可在这里管理的订阅", snapshot.subscriptions.filter(item => item.management_type === "MANAGED")],
    ["需要到商户管理的订阅", snapshot.subscriptions.filter(item => item.management_type === "DETECTED_ONLY")],
  ];
  for (const [title, items] of groups) {
    if (!items.length) continue;
    lines.push(`\n## ${title}（${items.length} 项）`, "", "| 订阅 | 费用 | 周期 | 最近扣费 | 下次续费 |", "| --- | --- | --- | --- | --- |");
    for (const item of items) {
      const pastEstimate = item.next_billing_is_estimated && item.next_billing_at && item.next_billing_at < snapshot.generated_at;
      const next = item.status === "CANCELLED" ? "已取消" : pastEstimate ? "待确认" : `${date(item.next_billing_at)}${item.next_billing_is_estimated ? "（预计）" : ""}`;
      lines.push(`| ${cell(item.merchant)}${item.plan_name ? ` · ${cell(item.plan_name)}` : ""} | ${item.contract_amount_display ?? item.last_charge_display} | ${item.billing_interval === "MONTHLY" ? "每月" : "每年"} | ${item.last_charge_date ? `${item.last_charge_display}（${item.last_charge_date}）` : "暂无扣费记录"} | ${next} |`);
    }
    lines.push("", title === "可在这里管理的订阅" ? "如需取消订阅，请进入左侧「订阅管理」，选择对应订阅并确认取消。" : "这些订阅根据扣费记录识别，请前往对应商户确认续费安排或取消订阅。");
  }
  lines.push("\n## 费用汇总", ...snapshot.monthly_cost_by_currency.map(item => `- 每月费用：${item.amount_display}`), ...(snapshot.annual_projected_cost_by_currency ?? []).map(item => `- 预计每年费用：${item.amount_display}`));
  if (snapshot.price_changes?.length) {
    lines.push("\n## 费用变化", ...snapshot.price_changes.map(item => `- ${cell(item.merchant)}：最近一期费用变化 ${item.price_change_display}${item.price_change_percent_display ? `（${item.price_change_percent_display}）` : ""}。`));
  }
  if (snapshot.upcoming_renewals?.length) {
    lines.push("\n## 即将续费", ...snapshot.upcoming_renewals.map(item => `- ${cell(item.merchant)}：${date(item.next_billing_at)}${item.next_billing_is_estimated ? "（预计）" : ""}，${item.contract_amount_display ?? item.last_charge_display}。`));
  }
  return lines.join("\n");
}
