import type { components } from "@banking/api-client";

type Risk = components["schemas"]["TransferRiskDecision"];
const riskLabels = { GREEN: "GREEN · 绿色", YELLOW: "YELLOW · 黄色", RED: "RED · 红色" };
export function RiskBadge({ level }: { level: components["schemas"]["BusinessRiskLevel"] }) {
  const colors = { GREEN: "bg-emerald-100 text-emerald-800", YELLOW: "bg-amber-100 text-amber-800", RED: "bg-red-100 text-red-800" };
  return <span className={`rounded-full px-2 py-1 text-xs font-semibold ${colors[level]}`}>{riskLabels[level]}</span>;
}
export function RiskDetails({ risk }: { risk: Risk }) {
  return <section aria-label="转账风险评估" className="mt-3 rounded-xl border border-slate-200 bg-white p-4">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold">风险等级</h3><RiskBadge level={risk.level} /></div>
    {risk.reason_codes.includes("RISK_ESCALATED_AT_COMMIT") && <p className="mt-3 rounded bg-red-50 p-2 text-xs text-red-800">风险已升级，当前资金支出规则要求强验证。</p>}
    {risk.reason_codes.includes("FUNDS_OUTFLOW_REQUIRES_REAUTH") && <p className="mt-3 text-xs font-semibold text-red-800">涉及资金支出，必须强验证。</p>}
    {risk.reason_codes.includes("PASSWORDLESS_LIMIT_REACHED") && <p className="mt-3 text-xs font-semibold text-red-800">本笔金额已达到或超过本人免密额度，需要强验证。</p>}
    {risk.reason_codes.includes("DAILY_TRANSFER_LIMIT_EXCEEDED") && <p className="mt-3 text-xs font-semibold text-red-800">含本笔的当日累计已超过1000元，需要强验证。</p>}
    <dl className="mt-3 grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-2 text-xs">
      <dt className="text-slate-500">本笔转账 · {risk.currency}</dt><dd className="text-right font-semibold">{risk.requested_amount_display}</dd>
      {risk.passwordless_limit_display && <><dt className="text-slate-500">本人单笔免密额度</dt><dd className="text-right">{risk.passwordless_limit_display}</dd></>}
      <dt className="text-slate-500">当日已成功</dt><dd className="text-right">{risk.daily_successful_total_display}</dd>
      <dt className="text-slate-500">当日执行中</dt><dd className="text-right">{risk.daily_in_flight_exposure_display}</dd>
      <dt className="text-slate-500">当日累计风险暴露（含本笔）</dt><dd className="text-right font-semibold">{risk.projected_daily_total_display}</dd>
      <dt className="text-slate-500">业务日期</dt><dd className="text-right">{risk.business_date}</dd>
    </dl>
    <p className="mt-3 text-xs">{risk.required_approval ? "✓ 需要用户确认" : "○ 无需用户确认"}</p>
    <p className="mt-1 text-xs">{risk.required_reauthentication ? "✓ 需要强身份验证" : "○ 无需强身份验证"}</p>
  </section>;
}
