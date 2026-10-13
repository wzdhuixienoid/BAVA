"use client";
import { WealthPurchaseEntry } from "@/features/wealth/WealthPurchaseEntry";
import { wealthConversationRequest } from "@/features/wealth/conversation-request";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import type { components } from "@banking/api-client";
import { api } from "@/lib/api/client";
import { WealthProductCard, WealthSources, WealthWorkflowCard, WealthOrderExplanation } from "@/features/wealth/WealthCards";
import { AuditTimeline } from "@/features/audit/AuditTimeline";
import { useWealthData } from "@/features/wealth/useWealthData";
import { queryTime } from "@/lib/presentation/time";



export default function WealthPage() {
  const {products, positions, orders, assessment, questionnaire, accounts, workflows, feature, refreshError, refresh} = useWealthData();
  const canNew = feature?.new_business_allowed ?? false;
  const resources = useMemo(() => ({products, accounts, positions, newBusinessAllowed:canNew}), [products, accounts, positions, canNew]);
  const [answers, setAnswers] = useState<string[]>(Array(8).fill(""));
  const [selected, setSelected] = useState<string[]>([]);
  const [needs, setNeeds] = useState("");
  const [amount, setAmount] = useState("");
  const [account, setAccount] = useState("");
  const [error, setError] = useState("");
  const [audit, setAudit] = useState<components["schemas"]["AuditTrace"] | null>(null);
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const draftKeys = useRef(new Map<string, string>());
  const completedDrafts = useRef(new Map<string, string>());
  const analysisConversations = useRef(new Map<string, string>());
  useEffect(() => {
    for (const [key, id] of completedDrafts.current) {
      if (workflows.some(w => w.workflow_id === id && ["SUCCEEDED", "FAILED", "CANCELLED"].includes(w.status))) {
        completedDrafts.current.delete(key); draftKeys.current.delete(key);
      }
    }
  }, [workflows]);
  async function act(action: () => Promise<unknown>) {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError("");
    try {await action(); await refresh();} catch(e) {setError(e instanceof Error ? e.message : "操作失败");}
    finally {pending.current = false; setBusy(false);}
  }
  async function analyzeInConversation(intent: "RECOMMENDATION" | "COMPARISON") {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError("");
    const content = wealthConversationRequest({
      intent, needs, amount,
      accountName: accounts.find(a => a.account_id === account)?.display_name,
      productNames: selected.map(id => products.find(p => p.product_id === id)?.name).filter((name): name is string => !!name),
    });
    try {
      let conversationId = analysisConversations.current.get(content);
      if (!conversationId) {
        const created = await api.createConversation({ title: intent === "COMPARISON" ? "理财产品对比" : "个性化理财推荐" });
        conversationId = created.conversation_id;
        analysisConversations.current.set(content, conversationId);
      }
      await api.postMessage(conversationId, content);
      window.location.assign(`/?conversation=${encodeURIComponent(conversationId)}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "暂时无法发起分析，请重试。");
      pending.current = false; setBusy(false);
    }
  }
  async function draft(direction: "PURCHASE" | "REDEEM", product_id: string, account_id?: string, redeem_all = false) {
    if (direction === "PURCHASE" && (!assessment || assessment.expired || !assessment.suitable)) {
      setError(!assessment || assessment.expired ? "购买理财前请先完成有效风险测评" : "当前测评结果不适合购买这些模拟产品");
      return;
    }
    const key = JSON.stringify([direction, product_id, account_id ?? account, redeem_all]);
    if (completedDrafts.current.has(key) || workflows.some(w => !["SUCCEEDED", "FAILED", "CANCELLED"].includes(w.status) && w.presentation?.wealth_state?.draft.direction === direction && w.presentation?.wealth_state?.draft.product_id === product_id && (!account_id || w.presentation?.wealth_state?.draft.account_id === account_id))) {setError("该交易草稿已创建，请在下方核对卡继续操作"); return;}
    if (!draftKeys.current.has(key)) draftKeys.current.set(key, crypto.randomUUID());
    await act(async () => {
      const created = await api.wealthCreate({creation_key:draftKeys.current.get(key), direction, product_id, account_id:account_id ?? (account || undefined), quantity:redeem_all ? positions.find(p => p.product_id === product_id && p.account_id === account_id)?.available_quantity : undefined, redeem_all});
      completedDrafts.current.set(key, created.workflow_id);
    });
  }
  return <main className="min-h-screen bg-slate-50"><div className="mx-auto max-w-6xl space-y-8 px-6 py-8">
    <header><Link href="/" className="float-right text-cyan-700 underline">返回工作台</Link><h1 className="text-3xl font-semibold">理财中心（模拟）</h1><p className="mt-2 text-sm text-slate-600">开放式净值型 · 无本金或收益保证 · 异步成交及到账 · 不另收持续管理费</p></header>
    <button disabled={busy} onClick={() => void refresh(true, true)} className="rounded border bg-white px-3 py-2 text-sm">刷新理财数据</button>
    {feature && !canNew && <p role="status" className="rounded border border-amber-200 bg-amber-50 p-3">{feature.reason}</p>}
    {refreshError && <p role="status" className="text-sm text-amber-800">{refreshError}</p>}
    {error && <p role="alert" className="rounded border border-red-200 bg-red-50 p-3 text-red-700">{error}</p>}
    <section id="risk-assessment" aria-label="风险测评" className="rounded-xl border bg-white p-5"><h2 className="text-xl font-semibold">风险测评</h2>
      {!assessment && <p className="mt-2 text-sm text-amber-800">购买理财前，请先由本人完成风险测评。你仍可浏览产品、资料和客观对比。</p>}
      {assessment && <p className="mt-2">{assessment.grade_display} · {assessment.expired ? "已失效，请重测" : `有效至 ${queryTime(assessment.expires_at)}`} · {assessment.suitable ? "适配风险不超过客户等级的产品" : "所有模拟产品均不适合"}</p>}
      {assessment?.reasons.map(r => <p key={r} className="text-sm text-amber-800">{r}</p>)}
      <details className="mt-3" open={!assessment || assessment.expired}><summary className="cursor-pointer">{assessment ? "重要信息变化或重新测评" : "开始测评"}</summary><p className="mt-2 text-xs text-slate-500">{questionnaire?.notice}</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">{questionnaire?.questions.map((q,i) => <label key={q.label} className="text-sm">{q.label}<select aria-label={q.label} value={answers[i]} onChange={e => setAnswers(a => a.map((v,j) => j === i ? e.target.value : v))} className="mt-1 block w-full rounded border p-2"><option value="">请本人选择</option>{q.options.map((o,j) => <option key={o} value={j}>{o}</option>)}</select></label>)}</div>
        <button disabled={!canNew || busy || !questionnaire || answers.some(a => a === "")} onClick={() => void act(() => api.wealthAssess({questionnaire_version:questionnaire?.version ?? "mock-v1",answers:answers.map(Number)}))} className="mt-3 rounded bg-cyan-700 px-4 py-2 text-white">提交测评</button>
      </details>
    </section>
    <section aria-label="模拟产品"><h2 className="text-xl font-semibold">模拟产品</h2>
      <div className="my-4 flex flex-wrap gap-3"><label className="text-sm">本人账户<select aria-label="推荐账户" value={account} onChange={e => setAccount(e.target.value)} className="ml-2 rounded border p-2"><option value="">可选账户</option>{accounts.map(a => <option key={a.account_id} value={a.account_id}>{a.display_name} · {a.balance_display}</option>)}</select></label><input aria-label="投资需求" placeholder="需求，例如稳健，一周内可能用钱" value={needs} onChange={e => setNeeds(e.target.value)} className="rounded border p-2"/><input aria-label="推荐金额" placeholder="可选金额（元）" value={amount} onChange={e => setAmount(e.target.value)} className="rounded border p-2"/><button disabled={busy || !assessment || assessment.expired || !assessment.suitable} onClick={() => void analyzeInConversation("RECOMMENDATION")} className="rounded bg-cyan-700 px-3 py-2 text-white">个性化推荐</button></div>
      <div className="grid gap-4 md:grid-cols-2">{products.map(p => <WealthProductCard key={p.product_id} product={p}><div className="mt-3 flex items-center gap-3"><label className="text-sm"><input type="checkbox" checked={selected.includes(p.product_id)} disabled={!selected.includes(p.product_id) && selected.length >= 4} onChange={e => setSelected(s => e.target.checked ? [...s,p.product_id] : s.filter(id => id !== p.product_id))}/> 加入对比</label><WealthPurchaseEntry product={{...p,purchase_allowed:p.purchase_allowed && !!assessment && !assessment.expired && assessment.suitable,purchase_block_reason:!assessment || assessment.expired ? "请先完成有效风险测评" : p.purchase_block_reason}} allowed={canNew} accounts={accounts} amount={amount} accountId={account} onRefresh={refresh}/></div></WealthProductCard>)}</div>
      <button disabled={busy || !selected.length} onClick={() => void analyzeInConversation("COMPARISON")} className="my-3 rounded border bg-white px-4 py-2">对比所选产品（最多4个）</button>
    </section>
    <section aria-label="我的持仓"><h2 className="text-xl font-semibold">我的持仓</h2>{!positions.length && <p className="mt-3 text-sm text-slate-500">暂无持仓，申购成交后显示份额。</p>}{positions.map(p => <div key={p.position_id} className="mt-3 rounded-xl border bg-white p-4"><h3 className="font-semibold">{p.name} · 原付款账户 {accounts.find(a => a.account_id === p.account_id)?.display_name ?? "本人账户"}</h3><p className="mt-2 text-sm">总份额 {p.shares_display} · 冻结 {p.frozen_display} · 可赎回 {p.available_display}</p><p className="text-sm">最新估值 {p.value_display ?? "暂无数据"} · {p.valued_at ? queryTime(p.valued_at) : "缺少已发布净值"}</p><p className="text-sm">待到账资金 {p.pending_display}（未计入可用余额或持仓估值）</p><button disabled={!canNew || busy || /^0\.0+$/.test(p.available_display)} onClick={() => void draft("REDEEM",p.product_id,p.account_id)} className="mt-2 rounded border px-3 py-1 text-sm">部分赎回并核对</button><button disabled={!canNew || busy || !p.available_quantity || /^0\.0+$/.test(p.available_quantity)} onClick={() => void draft("REDEEM",p.product_id,p.account_id,true)} className="ml-2 mt-2 rounded border px-3 py-1 text-sm">全部赎回</button></div>)}</section>
    <section aria-label="交易核对"><h2 className="text-xl font-semibold">交易核对与授权</h2>{workflows.filter(w => !orders.some(o => o.workflow_id === w.workflow_id && o.conversation_deleted) && w.status !== "SUCCEEDED" && w.status !== "CANCELLED" && (w.status !== "FAILED" || !orders.some(o => o.workflow_id === w.workflow_id))).map(w => <WealthWorkflowCard key={w.workflow_id} workflow={w} onRefresh={refresh} resources={resources}/>)}</section>
    <section aria-label="交易订单"><h2 className="text-xl font-semibold">交易订单</h2>{!orders.length && <p className="mt-3 text-sm text-slate-500">暂无订单，提交后显示受理及结算进度。</p>}{orders.map(o => <div key={o.order_id} className="mt-3 rounded-xl border bg-white p-4"><h3 className="font-semibold">{o.name} · {o.direction_display} · {o.status_display}</h3><p className="mt-2 text-sm">{o.quantity_display} · 交易日 {o.trade_date}</p><p className="text-sm">预计成交 {queryTime(o.confirm_at)} · 预计到账 {queryTime(o.settle_at)}</p><WealthOrderExplanation order={o}/>{o.actual && <p className="mt-2 text-sm">实际净值 {o.actual.nav_display} · 实际费用 {o.actual.fee_display} · 实际份额 {o.actual.shares_display} · {o.cash_result_label ?? (o.status_display.includes("待到账") ? "待到账金额" : "实际价款/到账金额")} {o.actual.net_display} · 余款退款 {o.actual.refund_display}</p>}<WealthSources sources={o.sources}/>{!o.conversation_deleted && <Link href={`/?conversation=${o.conversation_id ?? workflows.find(w => w.workflow_id === o.workflow_id)?.conversation_id ?? ""}`} className="mt-2 block text-xs text-cyan-700 underline">查看对话与处理过程</Link>}<button onClick={() => void act(async () => {const taskId=o.source_task_id ?? workflows.find(w => w.workflow_id===o.workflow_id)?.source_task_id; if(taskId) {setAudit(await api.getTaskAudit(taskId));}})} className="mt-2 text-xs text-cyan-700 underline">查看审计事件</button></div>)}</section>
    {audit && <div role="dialog" aria-label="理财审计" className="fixed inset-8 z-50 overflow-auto rounded border bg-white p-4"><button className="mb-4 rounded border p-2" onClick={() => setAudit(null)}>关闭审计</button><AuditTimeline trace={audit}/></div>}
  </div></main>;
}
