import type { components } from "@banking/api-client";

type Insight = components["schemas"]["ReportInsight"];

export function ReportInsights({ headline, insights }: { headline: string; insights: Insight[] }) {
  return (
    <section className="rounded-2xl bg-slate-950 p-6 text-white shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">智能洞察</p>
      <h2 className="mt-2 text-xl font-semibold">{headline}</h2>
      <div className="mt-5 grid gap-3 md:grid-cols-2">
        {insights.map((insight, index) => (
          <article key={`${insight.type}-${index}`} className="rounded-xl bg-white/10 p-4">
            <h3 className="font-semibold text-white">{insight.title}</h3>
            <p className="mt-2 text-sm leading-6 text-slate-300">{insight.narrative}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
