import { statusDisplay, tones } from "@/lib/presentation/status";

export function StatusBadge({ status }: { status: string }) {
  const display = statusDisplay(status);
  return <span title={display.description} className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-1 text-[11px] font-semibold ${tones[display.tone]}`}>
    <span aria-hidden="true">{display.icon}</span>{display.label}
  </span>;
}
