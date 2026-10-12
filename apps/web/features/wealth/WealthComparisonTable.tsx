import type {ReactNode} from "react";
import type {components} from "@banking/api-client";
import {queryTime} from "@/lib/presentation/time";

type Analysis = components["schemas"]["WealthAnalysis"];
type Candidate = Analysis["candidates"][number];

export function WealthComparisonTable({analysis}: {analysis: Analysis}) {
  const hasDesign = analysis.candidates.some(c => c.product.design_profile);
  const rows: {label: string; value: (c: Candidate) => ReactNode}[] = [
    ...(hasDesign ? [
      {label: "策略定位", value: (c: Candidate) => c.product.design_profile?.positioning ?? "尚未提供设计资料"},
      {label: "收益从哪里来", value: (c: Candidate) => c.product.design_profile?.return_sources.join("；") ?? "暂无资料"},
      {label: "主要波动风险", value: (c: Candidate) => c.product.design_profile?.risk_drivers.join("；") ?? "暂无资料"},
      {label: "参考观察期", value: (c: Candidate) => c.product.design_profile?.observation_label ?? "暂无资料"},
    ] : []),
    {label: "风险等级", value: c => <>{c.product.risk}{!c.product.purchase_allowed && <p className="mt-1 text-slate-500">{c.product.purchase_block_reason ?? "暂不能购买"}</p>}</>},
    {label: "起购 / 开放安排", value: c => <>{c.product.minimum_display}<br/>{c.product.open_display}</>},
    {label: "同预算费用（假设净值不变）", value: c => c.fee_scenario?.total_fee_display ?? `预算未提供；${c.product.fees_display}`},
    {label: "新申购最早现金到账", value: c => <>{queryTime(c.timing.earliest_cash_at)}<br/>预估，不保证到账</>},
  ];
  return <div aria-label="产品比较" className="space-y-2">
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full min-w-[600px] table-fixed border-collapse bg-white text-left text-xs leading-5">
        <caption className="px-3 py-2 text-left text-sm font-medium">同一条件下的产品对比</caption>
        <thead className="bg-slate-50"><tr>
          <th scope="col" className="w-32 border-t p-3">比较维度</th>
          {analysis.candidates.map(c => <th scope="col" key={c.fact_id} className="border-l border-t p-3">{c.product.name}</th>)}
        </tr></thead>
        <tbody>{rows.map(row => <tr key={row.label}>
          <th scope="row" className="border-t bg-slate-50 p-3 align-top font-medium">{row.label}</th>
          {analysis.candidates.map(c => <td key={c.fact_id} className="border-l border-t p-3 align-top">{row.value(c)}</td>)}
        </tr>)}</tbody>
      </table>
    </div>
    {hasDesign && <p className="text-xs text-slate-500">策略为模拟设计。观察期供分析参考，赎回以交易条款为准；历史合成净值不是该组合的回测。</p>}
  </div>;
}
