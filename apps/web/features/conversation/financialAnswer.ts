import { categoryLabels } from "../reports/presentation";
import { transactionTime } from "../../lib/presentation/time";

// Compatibility presentation for saved answers created before tool display fields.
export function localizeFinancialAnswer(content: string, outputs: Record<string, unknown>[]): string {
  const accountNames: Record<string, string> = {};
  for (const output of outputs) {
    Object.assign(accountNames, output.financial_account_names ?? {});
    const snapshot = output.analysis_snapshot as {
      top_transactions?: { transactions?: { account_id: string; account_display?: string }[] };
    } | undefined;
    for (const transaction of snapshot?.top_transactions?.transactions ?? []) {
      if (transaction.account_display) accountNames[transaction.account_id] = transaction.account_display;
    }
  }
  let result = content
    .replace("汇总（工具返回原值）", "汇总")
    .replace("以下为工具在该区间内返回的原值。", "")
    .replace(/^（分类合计与总额是否一致，请以工具返回字段为准，我未做任何自行计算。）\s*$/gm, "")
    .replace(/^.*[（(]share 为 0[–—-]1 的比例原值，未做换算。[）)].*(?:\n|$)/gm, "")
    .replace(/\b(?:FOOD|SHOPPING|TRAVEL|HOUSING|TRANSPORTATION|TRANSPORT|UTILITIES|SUBSCRIPTION|HEALTH|ENTERTAINMENT|OTHER)\b/g, (value) => categoryLabels[value])
    .replace(/\bacc_[a-zA-Z0-9_]+\b/g, (value) => accountNames[value] ?? "账户")
    .replace(/\bCNY\b/g, "人民币")
    .replace(/\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})/g, transactionTime)
    .replace(/(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{2}:\d{2})(?::\d{2})?\s*[（(](?:协调世界时|UTC)[）)]/g,
      (_, year, month, day, clock) => transactionTime(`${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}T${clock}:00Z`));
  const lines = result.split("\n");
  let shareColumn = -1;
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index];
    if (!line.trim().startsWith("|")) { shareColumn = -1; continue; }
    const cells = line.split("|");
    const header = cells.findIndex((cell) => cell.trim() === "占比");
    if (header >= 0) {
      shareColumn = header;
      cells[header] = " 占比 (%) ";
    } else if (shareColumn >= 0 && /^\s*0(?:\.\d+)?\s*$|^\s*1(?:\.0+)?\s*$/.test(cells[shareColumn] ?? "")) {
      // Round decimal text directly, keeping arbitrary precision of stored tool values.
      const value = cells[shareColumn].trim();
      const [whole, fraction = ""] = value.split(".");
      const digits = fraction.padEnd(5, "0");
      let hundredths = Number(whole) * 10000 + Number(digits.slice(0, 4));
      if (Number(digits[4]) >= 5) hundredths++;
      cells[shareColumn] = ` ${Math.floor(hundredths / 100)}.${String(hundredths % 100).padStart(2, "0")}% `;
    }
    lines[index] = cells.join("|");
  }
  result = lines.join("\n");
  return result;
}

export function requestsAnomalyAnalysis(content: string = ""): boolean {
  const intent = content.replace(/(?:不要|不用|无需|不需要|别)[^，。；\n]*?(?:异常|奇怪扣款|可疑|盗刷)[^，。；\n]*/g, "");
  return /异常|奇怪扣款|可疑|盗刷|不明扣款|重复扣(?:款|费)|不认识的(?:交易|扣款)/.test(intent);
}
