"use client";
import {useRef, useState} from "react";
import type {components} from "@banking/api-client";
import {api} from "@/lib/api/client";
import {WealthPurchaseEntry} from "./WealthPurchaseEntry";
import {queryTime} from "@/lib/presentation/time";

type Analysis = components["schemas"]["WealthAnalysis"];
import {WealthProductCard} from "./WealthCards";
import {WealthEvidencePanel} from "./WealthEvidencePanel";
export {WealthEvidencePanel,safeEvidenceSource} from "./WealthEvidencePanel";

export function WealthAnalysisCard({analysis,conversationId,onRefresh,accounts}: {analysis:Analysis;conversationId?:string;onRefresh?:()=>Promise<void>;accounts?:components["schemas"]["AccountBalanceResult"][]}) {
  const accountRequest=useRef<Promise<components["schemas"]["AccountBalanceResult"][]>|null>(null);
  function loadAccounts() {
    accountRequest.current ??= api.wealthAccounts().catch(e=>{accountRequest.current=null;throw e;});
    return accountRequest.current;
  }
  const states={NEEDS_ASSESSMENT:"需要测评",NEEDS_CLARIFICATION:"需要补充条件",CONDITIONAL:"先供你参考",MATCHED:"按已知条件匹配",NO_MATCH:"暂无适配产品",EDUCATION:"知识说明"};
  const n=analysis.needs;
  const response=analysis.customer_response;
  const legacyBudget = !n.amount ? n.raw?.match(/预算\s*(?:是|为|有|约|：|:)?\s*[\d,]+(?:\.\d+)?\s*(?:亿元?|万元?|元|[wW])/)?.[0] : null;
  const questions=(response?.questions ?? n.clarification_questions).filter(q=>!legacyBudget || !q.includes("投资多少"));
  return <section aria-label="理财分析" className="mt-3 space-y-4 text-slate-900">
    <p className="text-xs text-slate-500">模拟理财 · {analysis.result_kind === "CATALOGUE" ? "产品介绍" : states[analysis.status]} · {queryTime(analysis.reference_time)}</p>
    <p className="text-base font-medium leading-7">{response?.headline ?? analysis.conclusion}</p>
    {analysis.historical_reference && <p className="text-sm text-amber-900">{analysis.historical_reference}</p>}
    {!analysis.new_business_allowed && <p className="text-sm text-amber-900">已暂停新理财交易，已受理订单继续处理。</p>}
    {analysis.status === "NEEDS_ASSESSMENT" && <a href="/wealth" className="text-sm text-cyan-800 underline">前往理财中心完成风险测评</a>}
    {analysis.result_kind !== "EDUCATION" && <div className="text-sm text-slate-600">
      {(n.amount || legacyBudget || n.liquidity_raw) && <p>{n.amount ? `投资预算：${response?.budget_display ?? `${n.amount} 元`}` : legacyBudget}{n.liquidity_raw && ` · 用款安排：${n.liquidity_raw}`}</p>}
      {questions.map(q=><p key={q} className="mt-1 text-slate-900">{q}</p>)}
      {legacyBudget && (conversationId && onRefresh ? <WealthReanalyze conversationId={conversationId} request={n.raw} onRefresh={onRefresh} explanation="这条历史回复没有按该预算计算费用，可按当前条件重新分析。"/> : <p>这条历史回复没有按该预算计算费用，可以按当前条件重新分析。</p>)}
    </div>}
    {analysis.result_kind === "EDUCATION" ? (analysis.blocks.filter(b=>b.block_id!=="conclusion" && !b.block_id.startsWith("candidate-")).map(b=><div key={b.block_id} className="text-sm leading-6"><h3 className="font-medium">{b.title}</h3><p>{b.text}</p></div>)) : <details className="text-sm"><summary className="cursor-pointer text-cyan-800">了解相关理财知识</summary>{analysis.blocks.filter(b=>b.block_id!=="conclusion" && !b.block_id.startsWith("candidate-")).map(b=><div key={b.block_id} className="text-sm leading-6"><h3 className="font-medium">{b.title}</h3><p>{b.text}</p></div>)}</details>}
    {analysis.candidates.find(c=>c.fee_scenario)?.fee_scenario && <p className="text-xs text-slate-600">{analysis.candidates.find(c=>c.fee_scenario)!.fee_scenario!.assumption}</p>}
    {analysis.result_kind !== "EDUCATION" && <div aria-label="产品分析正文" className="space-y-3 text-sm leading-7">{response ? (response.paragraphs ?? []).map(p=><p key={p.block_id}>{p.text}</p>) : analysis.candidates.map(c=><div key={c.fact_id}>
      <p>{c.product.name}：{c.advantages.filter(a=>!/^目前只/.test(a)).join(" ")} {c.limitations.join(" ")}</p>
      <p className="text-slate-600">如果{c.unsuitable_when.join("，或")}，这款产品就不适合这笔资金。</p>
    </div>)}</div>}
    {analysis.result_kind !== "CATALOGUE" && analysis.candidates.length>1 && <details open={analysis.result_kind === "COMPARISON"}><summary className="cursor-pointer text-sm text-cyan-800">对比风险、费用和到账时间</summary><div className="mt-2 overflow-x-auto"><table className="w-full min-w-[600px] border-collapse bg-white text-left text-xs"><caption className="mb-2 text-left text-sm">同一条件下的产品对比</caption><thead><tr>{["产品","风险等级","起购 / 开放安排","同预算费用（假设净值不变）","新申购最早现金到账"].map(h=><th key={h} className="border p-2">{h}</th>)}</tr></thead><tbody>{analysis.candidates.map(c=><tr key={c.fact_id}><td className="border p-2">{c.product.name}</td><td className="border p-2">{c.product.risk}{!c.product.purchase_allowed && <><br/>{c.product.purchase_block_reason ?? "暂不能购买"}</>}</td><td className="border p-2">{c.product.minimum_display}<br/>{c.product.open_display}</td><td className="border p-2">{c.fee_scenario ? c.fee_scenario.total_fee_display : `预算未提供；${c.product.fees_display}`}</td><td className="border p-2">{queryTime(c.timing.earliest_cash_at)}<br/>预估，不保证到账</td></tr>)}</tbody></table></div></details>}
    <div className="grid gap-3 sm:grid-cols-2">{analysis.candidates.map(c=><WealthProductCard key={c.fact_id} product={c.product}>
      {analysis.result_kind!=="EXPLANATION" && <WealthPurchaseEntry product={c.product} allowed={analysis.new_business_allowed && analysis.status!=="NEEDS_ASSESSMENT"} creationKey={c.purchase_entry_key} conversationId={conversationId} accounts={accounts} loadAccounts={loadAccounts} amount={n.amount} accountId={n.account_id} onRefresh={onRefresh}/>}
    </WealthProductCard>)}</div>
    {analysis.result_kind !== "CATALOGUE" && analysis.candidates.map(c=><div key={c.fact_id} className="text-sm leading-6"><details><summary className="cursor-pointer text-cyan-800">{c.product.name}的费用、到账与历史情景</summary><div className="mt-2 space-y-2">{c.fee_scenario ? <><p>预算 {c.fee_scenario.budget_display} · 申购费 {c.fee_scenario.purchase_fee_display} · 赎回费 {c.fee_scenario.redeem_fee_display} · 合计 {c.fee_scenario.total_fee_display}</p><p>{c.fee_scenario.assumption} 参考净值 {c.fee_scenario.nav}（{c.fee_scenario.nav_date}）。</p></> : <p>尚未提供预算，仅展示费率：{c.product.fees_display}。</p>}<p>新申购：{c.timing.purchase.trade_date} 交易，{queryTime(c.timing.purchase.confirm_at)} 确认获得份额；最早 {c.timing.earliest_redeem_new.trade_date} 申请赎回，{queryTime(c.timing.earliest_redeem_new.confirm_at)} 成交，{queryTime(c.timing.earliest_cash_at)} 现金到账。</p><p>若已经持有：现在申请赎回，预计 {queryTime(c.timing.redeem_existing.settle_at)} 到账。</p><p>{c.timing.notice}</p><p>模拟历史窗口：{c.history.start_date ?? "暂无"} 至 {c.history.end_date ?? "暂无"} · 区间变化 {c.history.change_display ?? "暂无数据"} · 最大回撤 {c.history.drawdown_display ?? "暂无数据"}。{c.history.missing_reason}</p><p>{c.history.notice} 数据截至 {queryTime(c.history.data_as_of)}。</p></div></details></div>)}
    {analysis.degradation_reason && <p className="text-xs text-amber-900">{analysis.degradation_reason}</p>}
    {!!analysis.excluded_products?.length && <details><summary className="cursor-pointer text-sm">未进入候选的主要原因</summary>{analysis.excluded_products.map(p=><p key={p.product_id} className="mt-1 text-xs">{p.name}：{p.reasons.join("；")}</p>)}</details>}
    <WealthEvidencePanel evidence={analysis.evidence}/>
  </section>;
}

export function WealthReanalyze({conversationId,request,onRefresh,explanation="这条历史结果未保存详细分析依据，可按当前条件重新分析。"}: {conversationId:string;request:string;onRefresh:()=>Promise<void>;explanation?:string}) {
  const pending=useRef(false);const [done,setDone]=useState(false);const [error,setError]=useState("");
  return <div className="mt-3 text-sm"><p className="text-slate-500">{explanation}</p><button disabled={done} className="mt-2 rounded border px-3 py-2 text-cyan-800" onClick={()=>{if(pending.current || done)return;pending.current=true;setError("");void api.postMessage(conversationId,`请按当前条件重新分析理财推荐（只读）：${request}`).then(async()=>{setDone(true);await onRefresh();}).catch(()=>setError("重新分析暂时失败，请重试。")).finally(()=>{pending.current=false;});}}>{done ? "已发起新的只读分析" : "按当前条件重新分析"}</button>{error && <p role="alert">{error}</p>}</div>;
}
