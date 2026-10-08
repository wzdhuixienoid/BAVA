import { transactionTime } from "../../lib/presentation/time";

export const categoryLabels: Record<string, string> = {
  FOOD: "餐饮",
  SHOPPING: "购物",
  TRAVEL: "旅行",
  HOUSING: "住房",
  TRANSPORT: "通勤",
  TRANSPORTATION: "通勤",
  UTILITIES: "水电通信",
  SUBSCRIPTION: "订阅",
  HEALTH: "健康",
  ENTERTAINMENT: "娱乐",
  OTHER: "其他",
};

export function categoryLabel(category: string): string {
  return categoryLabels[category] ?? category;
}

export function periodLabel(period: string): string {
  const [year, month] = period.split("-");
  if (!month) return `${year}年年度`;
  return `${year}年${Number(month)}月`;
}

export function dateLabel(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));
}

export function dateTimeLabel(value: string): string {
  return transactionTime(value);
}
