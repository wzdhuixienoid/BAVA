// All displayed transaction timestamps use Beijing time, independent of browser locale.
export function queryTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  }).formatToParts(date);
  const field = (type: string) => parts.find((part) => part.type === type)?.value;
  return `${field("year")}-${field("month")}-${field("day")} ${field("hour")}:${field("minute")}:${field("second")}`;
}

export const transactionTime = queryTime;

export function currentMonth(date = new Date()): string {
  return queryTime(date.toISOString()).slice(0, 7);
}
