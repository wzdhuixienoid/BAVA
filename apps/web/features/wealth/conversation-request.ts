type AnalysisRequest = {
  intent: "RECOMMENDATION" | "COMPARISON";
  needs: string;
  amount: string;
  accountName?: string;
  productNames: string[];
};

export function wealthConversationRequest({ intent, needs, amount, accountName, productNames }: AnalysisRequest): string {
  const lines = [intent === "COMPARISON"
    ? `请对比以下模拟理财产品：${productNames.join("、")}，说明风险、费用与到账安排。`
    : "请根据我的需求提供个性化模拟理财推荐，说明选择理由、风险、费用与到账安排。"];
  if (needs.trim()) lines.push(`我的投资需求：${needs.trim()}`);
  if (amount.trim()) lines.push(`本次投资预算：${amount.trim()}元。`);
  if (accountName) lines.push(`请用${accountName}作为分析参考账户。`);
  lines.push("请先进行只读分析。");
  return lines.join("\n");
}
