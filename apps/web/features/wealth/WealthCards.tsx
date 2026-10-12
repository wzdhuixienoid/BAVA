"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import type { components } from "@banking/api-client";
import { api } from "@/lib/api/client";
import { ReauthenticationForm } from "@/features/workflows/ReauthenticationForm";
import { WorkflowTimeline } from "@/features/workflows/WorkflowTimeline";
import { wealthReason } from "./answer";
import { WealthEvidencePanel } from "./WealthEvidencePanel";
import { queryTime } from "@/lib/presentation/time";

type Product = components["schemas"]["WealthProductResult"];
type Workflow = components["schemas"]["Workflow"];

export function WealthSources({sources}: {sources: string[]}) {
  const [doc, setDoc] = useState<components["schemas"]["WealthKnowledgeResult"] | null>(null);
  const [error, setError] = useState("");
  return <div className="mt-2 flex flex-wrap gap-2 text-xs">
    {sources.filter(source => /^\/api\/v1\/wealth\/documents\/[a-zA-Z0-9:_-]+$/.test(source)).map((source) => <button key={source} className="text-cyan-700 underline" onClick={() => {
      setError("");
      const id = source.split("/").pop()!;
      void api.wealthDocument(id).then(setDoc).catch(e => setError(e.message === "Failed to fetch" ? "暂时无法加载资料，请重试" : e.message));
    }}>{({"1":"产品说明书", "2":"风险提示", "3":"交易说明"} as Record<string,string>)[source.split(":").at(-1)!] ?? "产品资料"}</button>)}
    {error && <p role="alert">{error}</p>}
    {doc && <div role="dialog" aria-label="模拟产品资料" className="fixed inset-8 z-50 overflow-auto rounded-xl border bg-white p-6 shadow-xl sm:inset-x-1/4">
      <button onClick={() => setDoc(null)} className="float-right rounded border px-3 py-1">关闭资料</button>
      <h3 className="text-lg font-semibold">{doc.section}</h3><p className="mt-4 whitespace-pre-wrap text-sm leading-7">{doc.content}</p>
      <p className="mt-4 break-all text-xs text-slate-500">模拟产品资料 · {/^v\d+$/.test(doc.version) ? `第${doc.version.slice(1)}版` : "当前资料版本"}</p>
    </div>}
  </div>;
}

export function WealthProductCard({product, children}: {product: Product; children?: React.ReactNode}) {
  return <article className="rounded-xl border bg-white p-5"><h3 className="font-semibold">{product.name}（模拟）</h3>
    {product.design_profile && <p className="mt-2 text-sm text-slate-600">{product.design_profile.positioning}</p>}
    <p className="mt-2 text-sm">{product.risk} · 起购 {product.minimum_display}</p><p className="mt-1 text-sm">{product.open_display}</p>
    <p className="mt-1 text-sm">净值 {product.nav_display ?? "暂无数据"} · {product.nav_date ?? "暂无日期"}</p>
    <p className="mt-1 text-xs text-slate-500">{product.fees_display} · 不另收持续管理费</p>
    <p className="mt-1 text-xs">近30日 {product.change_display ?? "暂无数据"} · 最大回撤 {product.drawdown_display ?? "暂无数据"}</p>
    {product.missing_reason && <p className="text-xs text-slate-500">{product.missing_reason}</p>}
    <WealthSources sources={product.sources}/>{children}
  </article>;
}

export function WealthResultCard({result}: {result: components["schemas"]["WealthReadResult"]}) {
  return <section className="mt-3 space-y-3"><p className="text-xs text-slate-500">模拟理财 · 无本金或收益保证</p>
    {result.products?.map(p => <WealthProductCard key={p.product_id} product={p}/>)}
    {Object.entries(result.selected_reasons ?? {}).map(([id,reasons]) => <p key={id} className="text-xs text-slate-600">{result.products?.find(p => p.product_id===id)?.name}：{reasons.map(wealthReason).join("；")}</p>)}
    {result.reasons?.map(r => <p key={r} className="text-sm">{wealthReason(r)}</p>)}
    {!result.evidence_sources?.length && result.evidence?.map(e => <div key={e.document_id} className="rounded border p-3"><p className="text-sm">{e.content}</p><WealthSources sources={[e.source]}/></div>)}
    {Boolean(result.evidence_sources?.length) && <WealthEvidencePanel evidence={result.evidence_sources!}/>}
    {result.positions?.map(p => <p key={p.position_id}>{p.name} · 可赎回 {p.available_display} 份 · 估值 {p.value_display ?? "暂无数据"} · 待到账 {p.pending_display}</p>)}
    {result.orders?.map(o => <div key={o.order_id}><p>{o.name} · {o.direction_display} · {o.status_display}</p><WealthOrderExplanation order={o}/>{o.conversation_id && <Link href={`/?conversation=${o.conversation_id}`} className="text-xs underline">查看对话与处理过程</Link>}</div>)}
    <Link href="/wealth" className="text-xs text-cyan-700 underline">打开理财中心</Link>
  </section>;
}

type WealthResources = {
  products: Product[];
  accounts: components["schemas"]["AccountBalanceResult"][];
  positions: components["schemas"]["WealthPositionResult"][];
  newBusinessAllowed: boolean;
};

export function WealthWorkflowCard({workflow, onRefresh, resources}: {workflow: Workflow; onRefresh: () => Promise<void>; resources?: WealthResources}) {
  const state = workflow.presentation?.wealth_state;
  const [products, setProducts] = useState<Product[]>([]);
  const [accounts, setAccounts] = useState<components["schemas"]["AccountBalanceResult"][]>([]);
  const [positions, setPositions] = useState<components["schemas"]["WealthPositionResult"][]>([]);
  const [product, setProduct] = useState(state?.draft.product_id ?? "");
  const [account, setAccount] = useState(state?.draft.account_id ?? "");
  const [amount, setAmount] = useState(state?.draft.quantity ?? "");
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);
  const [dirty, setDirty] = useState(false);
  const [localAllowed, setLocalAllowed] = useState(true);
  const canNew = resources?.newBusinessAllowed ?? localAllowed;
  useEffect(() => {
    if (!dirty) {setProduct(state?.draft.product_id ?? ""); setAccount(state?.draft.account_id ?? ""); setAmount(state?.draft.quantity ?? "");}
  }, [state?.draft.product_id, state?.draft.account_id, state?.draft.quantity, dirty]);
  const [error, setError] = useState("");
  useEffect(() => {
    if (resources) {setProducts(resources.products); setAccounts(resources.accounts); setPositions(resources.positions); return;}
    void Promise.all([api.wealthProducts(), api.wealthAccounts(), api.wealthPositions(), api.wealthStatus()]).then(([p,a,s,f]) => {setProducts(p); setAccounts(a); setPositions(s); setLocalAllowed(f.new_business_allowed);}).catch(e => setError(e.message));
  }, [resources, workflow.workflow_id]);
  async function act(action: () => Promise<unknown>) {
    if (submitting.current) return;
    submitting.current = true; setBusy(true); setError("");
    try {await action(); setDirty(false); await onRefresh();}
    catch(e) {
      await onRefresh();
      const message = e instanceof Error ? e.message : "操作失败";
      if (message.includes("409")) {setDirty(false); setError("交易已更新，已刷新最新内容，请重新核对；不会自动重试提交");}
      else setError(message.includes("失效") ? `${message}。请重新核对、确认和强验证` : message);
    } finally {submitting.current = false; setBusy(false);}
  }
  if (!state) return <p>正在读取理财流程…</p>;
  const review = state.review;
  const purchase = state.draft.direction === "PURCHASE";
  const editable = ["WAITING_FOR_INPUT", "READY_FOR_REVIEW", "REAUTH_REQUIRED", "READY_FOR_COMMIT"].includes(workflow.status);
  const status = {DRAFT:"草稿", WAITING_FOR_INPUT:"待补全", VALIDATING:"校验中", READY_FOR_REVIEW:"待核对确认", REAUTH_REQUIRED:"待强验证", READY_FOR_COMMIT:"待提交", COMMITTING:"已提交，等待成交或到账", SUCCEEDED:"最终完成", FAILED:"明确失败", CANCELLED:"已取消"}[workflow.status];
  const allowedAccounts = purchase ? accounts : accounts.filter(a => positions.some(p => p.product_id === product && p.account_id === a.account_id));
  if (purchase && editable && state.purchase_entry_allowed === false) return <section className="mt-3 rounded-xl border border-cyan-100 bg-cyan-50 p-4">
    <p className="font-semibold">购买理财前，请先完成有效风险测评</p>
    <p className="mt-2 text-sm">{state.purchase_entry_block_reason}</p>
    <Link href="/wealth#risk-assessment" className="mt-2 block text-sm text-cyan-800 underline">前往理财中心查看并完成风险测评</Link>
    <p className="mt-2 text-xs text-slate-600">这份旧草稿尚未提交，未扣款；测评完成后需重新核对和授权。</p>
    <button disabled={busy} onClick={() => void act(() => api.cancelWorkflow(workflow.workflow_id, workflow.version))} className="mt-3 rounded border bg-white px-3 py-2 text-sm">取消草稿</button>
    <Link href={`/?conversation=${workflow.conversation_id}`} className="ml-3 text-xs text-cyan-700 underline">查看办理记录</Link>
    {error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
  </section>;
  return <section className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-4">
    <h3 className="font-semibold">模拟理财{purchase ? "申购" : "赎回"} · {status}</h3>
    {!canNew && <p className="mt-2 text-sm">已暂停新理财交易，已受理订单继续处理；未提交草稿可取消。</p>}
    {state.validation_message && <p className="mt-2 text-sm text-amber-900">{state.validation_message}</p>}
    {workflow.operation_summary?.status === "UNKNOWN" && <p className="text-sm">结果确认中，资金或份额仍冻结，请勿重复提交。</p>}
    {review && <div className="mt-3 space-y-1 text-sm"><p>{review.name} · {review.quantity_display}</p><p>交易账户：{review.account_display} · {review.account_masked}</p><p>估算费用：{review.fee_display}</p><p>{purchase ? "估算份额" : "估算到账"}：{purchase ? review.shares_display : review.net_display}</p><p>交易日：{review.trade_date} · 预计成交：{queryTime(review.confirm_at)}</p><p>预计到账：{queryTime(review.settle_at)}</p><p className="text-amber-900">{review.notice}</p><WealthSources sources={review.sources}/></div>}
    {editable && canNew && <details className="mt-3" open={!review}><summary className="cursor-pointer text-sm">补全或修改交易（修改后重新授权）</summary>
      <label className="mt-2 block text-xs">模拟产品<select aria-label="模拟产品" value={product} onChange={e => {setDirty(true); setProduct(e.target.value); if(!purchase) setAccount("");}} className="ml-2 rounded border p-2"><option value="">请选择</option>{products.map(p => <option key={p.product_id} value={p.product_id}>{p.name}</option>)}</select></label>
      <label className="mt-2 block text-xs">{purchase ? "本人付款账户" : "本人原付款账户"}<select aria-label="交易账户" value={account} onChange={e => {setDirty(true); setAccount(e.target.value);}} className="ml-2 rounded border p-2"><option value="">请选择</option>{allowedAccounts.map(a => <option key={a.account_id} value={a.account_id}>{a.display_name} · 可用 {a.balance_display}</option>)}</select></label>
      <label className="mt-2 block text-xs">{purchase ? "申购总金额（元）" : "赎回份额"}<input aria-label="交易数量" inputMode="decimal" value={amount} onChange={e => {setDirty(true); setAmount(e.target.value);}} className="ml-2 rounded border p-2"/></label>
      <button disabled={busy || !product || !account || !amount} className="mt-2 rounded border bg-white px-3 py-2 text-sm" onClick={() => void act(() => api.wealthEdit(workflow.workflow_id,{expected_version:workflow.version, redeem_all:false, product_id:product, account_id:account, quantity:amount}))}>保存并核对</button>
    </details>}
    {dirty && <p className="mt-2 text-sm">有未保存修改，请先保存并核对。</p>}
    {editable && canNew && review && <button disabled={busy || dirty} onClick={() => void act(() => api.approveTransfer(workflow.workflow_id, workflow.version))} className="mt-3 rounded bg-amber-700 px-3 py-2 text-sm text-white">{workflow.status === "READY_FOR_REVIEW" ? "我已核对，确认交易" : "重新核对并确认"}</button>}
    {canNew && !dirty && workflow.status === "REAUTH_REQUIRED" && <ReauthenticationForm workflow={workflow} busy={busy} act={act}/>}
    {canNew && workflow.status === "READY_FOR_COMMIT" && <button disabled={busy || dirty || workflow.reauth_summary?.status !== "VERIFIED"} onClick={() => void act(() => api.commitTransfer(workflow.workflow_id, workflow.version))} className="ml-2 mt-3 rounded bg-cyan-700 px-3 py-2 text-sm text-white">提交{purchase ? "申购" : "赎回"}</button>}
    {editable && <button disabled={busy} onClick={() => void act(() => api.cancelWorkflow(workflow.workflow_id, workflow.version))} className="ml-2 rounded border px-3 py-2 text-sm">取消草稿</button>}
    <WorkflowTimeline workflow={workflow}/><Link href={`/?conversation=${workflow.conversation_id}`} className="mt-2 block text-xs text-cyan-700 underline">查看办理记录</Link><Link href="/wealth" className="mt-2 block text-xs text-cyan-700 underline">查看持仓和订单</Link>
    {error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
  </section>;
}

export function WealthReceipt({workflow}: {workflow: Workflow}) {
  const [order, setOrder] = useState<components["schemas"]["WealthOrderResult"] | null>(null);
  useEffect(() => {void api.wealthOrders().then(rows => setOrder(rows.find(o => o.workflow_id === workflow.workflow_id) ?? null));}, [workflow.workflow_id]);
  return <section className="rounded-xl border border-emerald-200 bg-emerald-50 p-4"><h3 className="font-semibold">模拟理财最终完成</h3>
    {order && <><p>{order.name} · {order.direction_display} · {order.status_display}</p><p className="mt-2 text-sm">实际净值 {order.actual?.nav_display} · 实际费用 {order.actual?.fee_display} · 实际份额 {order.actual?.shares_display} · {order.cash_result_label ?? "实际价款/到账金额"} {order.actual?.net_display} · 余款退款 {order.actual?.refund_display}</p><WealthSources sources={order.sources}/></>}
    <WorkflowTimeline workflow={workflow}/><Link href="/wealth" className="mt-2 block text-xs text-cyan-700 underline">查看完整订单及持仓</Link>
  </section>;
}

export function WealthOrderExplanation({order}: {order: components["schemas"]["WealthOrderResult"]}) {
  const fallback = order.unknown ? "结果仍在确认，占用保留，继续查询原订单" : order.status_display;
  return <div className="mt-2 space-y-1 text-sm">
    {order.conversation_deleted && <p className="text-slate-500">原对话已删除，订单与办理记录仍保留。</p>}
    <p>{order.user_reason ?? fallback}</p>
    {order.last_known_stage && <p>当前进度：{order.last_known_stage}</p>}
    {order.next_step && <p>下一步：{order.next_step}</p>}
    {order.next_processing_at && <p>预计下次更新：{queryTime(order.next_processing_at)}</p>}
  </div>;
}
