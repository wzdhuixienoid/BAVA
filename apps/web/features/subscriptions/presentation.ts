import { transactionTime } from "../../lib/presentation/time";

export function dateTime(value?: string | null) {
  if (!value) return "—";
  return transactionTime(value);
}
