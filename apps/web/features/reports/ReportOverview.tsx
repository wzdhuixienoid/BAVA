import type { components } from "@banking/api-client";

type Overview = components["schemas"]["ReportOverview"];

export function ReportOverview({ overview }: { overview: Overview }) {
  const cards = [
    ["总支出", overview.total_spending_display],
    ["总收入", overview.total_income_display],
    ["消费笔数", String(overview.transaction_count)],
  ];

  return (
    <section className="grid gap-4 sm:grid-cols-3" aria-label="报告概览">
      {cards.map(([label, value]) => (
        <div key={label} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <p className="text-sm text-slate-500">{label}</p>
          <p className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">{value}</p>
        </div>
      ))}
    </section>
  );
}
