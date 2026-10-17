"use client";
import { useEffect,useRef,useState } from "react";
import type { components } from "@banking/api-client";
import { api } from "@/lib/api/client";
import { queryTime } from "@/lib/presentation/time";
import { TransferWorkflowCard } from "@/features/workflows/transfer/TransferWorkflowCard";
import {validateDraft,serverFieldError,participantNames,type FieldErrors,type DraftFields} from "./validation";
import type { AARequest,AAAccount } from "./types";

const labels:Record<string,string> = {DRAFT:"待核对",PUBLISHED:"待收款",PARTIAL:"部分收款",PARTIAL_CLOSED:"部分收款，含已关闭份额",COLLECTED:"已收齐",PENDING:"待付款",PROCESSING:"处理中",UNKNOWN:"结果未知",PAID:"已付款",SELF_PAID:"自己承担",REJECTED:"已拒绝",CANCELLED:"已取消",EXPIRED:"已过期",FAILED:"付款失败"};
export function AARequestCard({requestId, initialRequest, onDeleted}:{requestId:string; initialRequest?:AARequest; onDeleted?:(requestId:string)=>void}) {
  const syncedDraft = useRef<string | null>(null);
  const [deleteVersion,setDeleteVersion]=useState<number | null>(null);
  const [withdrawal,setWithdrawal]=useState<{share_id:string;display_name:string;amount:string;version:number} | null>(null);
  const [row,setRow]=useState<AARequest | null>(initialRequest ?? null);
  const [accounts,setAccounts]=useState<AAAccount[]>([]);
  const [workflow,setWorkflow]=useState<components["schemas"]["Workflow"] | null>(null);
  const [total,setTotal]=useState(""); const [people,setPeople]=useState("");
  const [self,setSelf]=useState(""); const [remark,setRemark]=useState("");
  const [account,setAccount]=useState(""); const [deadline,setDeadline]=useState("");
  const [manual,setManual]=useState(""); const [error,setError]=useState(""); const [busy,setBusy]=useState(false);
  const [checked,setChecked]=useState(false);
  const [serverErrors,setServerErrors]=useState<FieldErrors>({});
  useEffect(()=>{if(row?.deleted_from_list)return;let active=true; const refresh=()=>api.getAA(requestId).then(value=>{if(active)setRow(value);}).catch(e=>{if(active)setError(String(e));});void refresh();void api.aaAccounts().then(value=>{if(active)setAccounts(value);}).catch(e=>{if(active)setError(String(e));});const timer=setInterval(()=>void refresh(),3000);return()=>{active=false;clearInterval(timer);};},[requestId,row?.deleted_from_list]);
  useEffect(()=>{const version=row?`${row.request_id}:${row.version}`:null;if(row?.draft&&syncedDraft.current!==version){syncedDraft.current=version;setTotal(row.draft.intent.total??"");setPeople(row.draft.intent.participants.join("、"));setSelf(row.draft.intent.initiator_participates === null ? "" : String(row.draft.intent.initiator_participates));setRemark(row.draft.intent.remark);setAccount(row.draft.collection_account_id??"");setDeadline(row.deadline ? queryTime(row.deadline) : "");setManual(row.draft.intent.manual_amounts?Object.entries(row.draft.intent.manual_amounts).map(([name,value])=>`${name}=${value}`).join("、"):"");}},[row]);
  async function refresh(){setRow(await api.getAA(requestId));if(workflow)setWorkflow(await api.getWorkflow(workflow.workflow_id));}
  async function act(action:()=>Promise<unknown>){setBusy(true);setError("");try{await action();await refresh();}catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy(false);}}
  async function deleteRequest() {
    if(deleteVersion===null||busy||!row)return;
    setBusy(true);setError("");
    try {
      await api.deleteAA(requestId,deleteVersion);
      setRow({...row,can_delete:false,deleted_from_list:true});
      setDeleteVersion(null);onDeleted?.(requestId);
    } catch(e) {
      setDeleteVersion(null);
      setError(e instanceof Error?e.message:String(e));
      try {await refresh();} catch {/* Keep the delete failure visible; the user can retry after refresh. */}
    } finally {setBusy(false);}
  }
  const fields:DraftFields={total,people,self,account,remark,deadline,manual};
  const fieldErrors=checked?{...serverErrors,...validateDraft(fields,accounts.map(a=>a.account_id))}:{};
  function fieldProps(name:keyof DraftFields) {
    return {"aria-invalid":Boolean(fieldErrors[name]),"aria-describedby":fieldErrors[name]?`aa-${requestId}-${name}-error`:undefined,
      className:`block w-full rounded border p-2 ${fieldErrors[name]?"border-red-500 bg-red-50 focus:outline-red-500":"border-slate-200"}`};
  }
  function hint(name:keyof DraftFields) {return fieldErrors[name]&&<span id={`aa-${requestId}-${name}-error`} className="mt-1 block text-xs text-red-700">{fieldErrors[name]}</span>;}
  async function checkDraft() {
    if(!row)return;
    setChecked(true);setServerErrors({});setError("");
    if(Object.keys(validateDraft(fields,accounts.map(a=>a.account_id))).length) {
      setError("请修改红框中的资料，再核对分摊。");return;
    }
    setBusy(true);
    try {
      const manual_amounts=manual.trim()?Object.fromEntries(participantNames(manual).map(item=>item.split("=").map(x=>x.trim()))):null;
      const updated=await api.updateAA(requestId,row.version,{currency:row.draft?.intent.currency,total:total.trim(),participants:participantNames(people),initiator_participates:self==="true",remark:remark.trim(),manual_amounts},account,`${deadline.trim().replace(" ","T")}+08:00`);
      setRow(updated);
      if(updated.required_input) {
        setServerErrors(serverFieldError(updated.required_input));
        setError("分摊尚未通过核对，请修改提示的资料后重试。");
      } else setChecked(false);
    } catch(e) {
      const message=e instanceof Error?e.message:String(e);
      setServerErrors(serverFieldError(message));setError(message);
    } finally {setBusy(false);}
  }
  if(!row)return <p>加载 AA 请求…</p>;
  if(row.deleted_from_list)return <p className="rounded-xl border bg-slate-50 p-4 text-sm text-slate-500">这项已完全取消的 AA 收款已从列表删除，历史记录和审计保留。</p>;
  const snapshot=row.snapshot??row.preview;
  const draftDirty = Boolean(row.draft && (total !== (row.draft.intent.total ?? "") || people !== row.draft.intent.participants.join("、") || self !== (row.draft.intent.initiator_participates === null ? "" : String(row.draft.intent.initiator_participates)) || remark !== row.draft.intent.remark || account !== (row.draft.collection_account_id ?? "") || deadline !== queryTime(row.deadline) || manual !== (row.draft.intent.manual_amounts ? Object.entries(row.draft.intent.manual_amounts).map(([name,value])=>`${name}=${value}`).join("、") : "")));
  return <section id={`aa-${requestId}`} className="rounded-xl border border-cyan-200 bg-white p-4"><div className="flex justify-between"><h2 className="font-semibold">AA 收款 · {labels[row.status]}</h2><a href="/aa" className="text-xs text-cyan-700 underline">站内参与者与历史</a></div><p className="mt-2 text-xs text-slate-500">仅为站内 Mock 请求。发布不扣款，各参与者独立确认并强验证付款。不发送短信或自动催收。</p>
    {row.is_initiator&&row.status==="DRAFT"&&<form noValidate onSubmit={e=>{e.preventDefault();void checkDraft();}} className="my-3 grid gap-3 text-sm sm:grid-cols-2">
      <label>总额（元）<input value={total} onChange={e=>{setTotal(e.target.value);setServerErrors({});}} placeholder="" {...fieldProps("total")} />{hint("total")}</label>
      <label>参与者（只填写其他人，用顿号分隔）<input value={people} onChange={e=>{setPeople(e.target.value);setServerErrors({});}} placeholder="张三、李四、王五" {...fieldProps("people")} />{hint("people")}</label>
      <label>发起者是否参与<select value={self} onChange={e=>{setSelf(e.target.value);setServerErrors({});}} {...fieldProps("self")}><option value="">请选择</option><option value="true">我也参与</option><option value="false">我不参与</option></select>{hint("self")}</label>
      <label>收款账户<select value={account} onChange={e=>{setAccount(e.target.value);setServerErrors({});}} {...fieldProps("account")}><option value="">请选择</option>{accounts.map(a=><option value={a.account_id} key={a.account_id}>{a.display_name} {a.masked_number}</option>)}</select>{hint("account")}</label>
      <label>主题备注<input value={remark} onChange={e=>{setRemark(e.target.value);setServerErrors({});}} placeholder="" {...fieldProps("remark")} />{hint("remark")}</label>
      <label>截止时间<input value={deadline} onChange={e=>{setDeadline(e.target.value);setServerErrors({});}} placeholder="2026-10-15 21:22:00" {...fieldProps("deadline")} />{hint("deadline")}</label>
      <label className="sm:col-span-2">手动金额（选填，留空平均分摊）<input value={manual} onChange={e=>{setManual(e.target.value);setServerErrors({});}} placeholder="张三=40、李四=30、我=30" {...fieldProps("manual")} />{hint("manual")}</label>
      <button type="submit" disabled={busy} className="rounded bg-slate-900 p-2 text-white">{busy?"正在核对…":"核对分摊"}</button>
    </form>}
    {snapshot&&<div className="my-3 space-y-1 text-sm"><p>主题：{snapshot.remark||"AA 收款"}</p><p>总额 ¥{snapshot.total} · 收款账户 {snapshot.collection_account.display_name} {snapshot.collection_account.masked_number}</p><p>截止：{queryTime(snapshot.deadline)}</p>{!row.snapshot&&snapshot.participants.map(p=><p key={p.display_name}>{p.display_name}：¥{p.amount} {p.self_paid?"自己承担":"待请求"}</p>)}</div>}
    {row.is_initiator && (snapshot?.participants?.some(p=>p.self_paid) || row.shares?.some(s=>s.status==="SELF_PAID")) && <p className="mb-3 text-sm text-slate-600">你的份额记为自己承担，无需在这里付款；系统不会扣款或向自己转账，只向其他参与者收款。</p>}
    {row.snapshot && row.is_initiator && row.status!=="CANCELLED" && <p className="mb-3 text-sm text-slate-600">其他参与者需以自己的身份进入“AA 收款与付款”，选择付款账户，再独立确认并完成强验证。</p>}
    {row.is_initiator&&row.status==="DRAFT"&&row.preview&&<button disabled={busy || draftDirty} className="rounded bg-cyan-700 px-4 py-2 text-sm text-white" onClick={()=>void act(()=>api.publishAA(requestId,row.version))}>确认发布 AA 请求（不扣款）</button>}
    {draftDirty && <p className="mb-2 text-xs text-amber-800">资料已修改，请先点击“核对分摊”，再按更新后的逐人金额确认发布。</p>}
    {row.snapshot&&<><div className="mb-3 rounded bg-slate-50 p-3 text-sm">{row.status==="CANCELLED"?<>原应收 ¥{row.receivable} · 已收 ¥{row.received} · 全部收款份额已取消 · 自己承担 ¥{row.self_paid}</>:<>应收 ¥{row.receivable} · 已收 ¥{row.received} · 未收 ¥{row.outstanding} · 自己承担 ¥{row.self_paid}</>}</div>{row.shares?.map(s=><div key={s.share_id} className="flex flex-wrap items-center gap-3 border-t py-3 text-sm"><strong>{s.display_name}</strong><span>¥{s.amount} · {labels[s.status]}</span>{s.is_mine&&s.status==="PENDING"&&<><select aria-label="我的付款账户" value={account} onChange={e=>setAccount(e.target.value)} className="rounded border p-1"><option value="">选择我的付款账户</option>{accounts.map(a=><option key={a.account_id} value={a.account_id}>{a.display_name} {a.masked_number} · ¥{a.available_balance}</option>)}</select><button disabled={busy||!account} className="text-cyan-700 underline" onClick={()=>void act(async()=>setWorkflow(await api.payAA(s.share_id,row.version,account)))}>核对并付款</button><button disabled={busy} onClick={()=>void act(()=>api.closeAAShare(s.share_id,"reject",row.version))}>拒绝付款</button></>}{row.is_initiator&&s.status==="PENDING"&&<button disabled={busy} onClick={()=>{setError("");setWithdrawal({share_id:s.share_id,display_name:s.display_name,amount:s.amount,version:row.version});}} className="text-red-700">撤回收款请求</button>}{s.is_mine&&s.workflow_id&&<button onClick={()=>void act(async()=>setWorkflow(await api.getWorkflow(s.workflow_id!)))} className="text-cyan-700 underline">{s.status==="UNKNOWN"?"查询原操作":"付款详情"}</button>}</div>)}</>}
    {row.is_initiator&&row.can_delete&&<button disabled={busy} onClick={()=>{setError("");setDeleteVersion(row.version);}} className="mt-3 rounded border border-red-200 px-3 py-2 text-sm text-red-700 hover:bg-red-50">删除收款</button>}
    {deleteVersion!==null&&<div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"><div role="dialog" aria-modal="true" aria-labelledby={`aa-delete-${requestId}`} className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl"><h3 id={`aa-delete-${requestId}`} className="font-semibold">删除已取消的收款？</h3><p className="mt-3 text-sm text-slate-600">这项收款的全部份额已取消。删除后将从你的列表移除，历史记录和审计会保留。</p><div className="mt-4 flex justify-end gap-3"><button autoFocus disabled={busy} onClick={()=>setDeleteVersion(null)} className="rounded border px-3 py-2 text-sm">保留收款</button><button disabled={busy} onClick={()=>void deleteRequest()} className="rounded bg-red-700 px-3 py-2 text-sm text-white">{busy?"正在删除…":"确认删除"}</button></div></div></div>}
    {withdrawal && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"><div role="dialog" aria-modal="true" aria-labelledby="aa-withdraw-title" aria-describedby="aa-withdraw-description" className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl"><h3 id="aa-withdraw-title" className="font-semibold">撤回 {withdrawal.display_name} 的收款请求？</h3><p id="aa-withdraw-description" className="mt-3 text-sm text-slate-600">撤回后，对方无需再支付这笔 ¥{withdrawal.amount}。金额不会自动分摊给其他人，已付款记录会保留。正在付款或结果未知的请求不能撤回。</p><div className="mt-4 flex justify-end gap-3"><button autoFocus disabled={busy} onClick={()=>{setWithdrawal(null);setError("");}} className="rounded border px-3 py-2 text-sm">保留请求</button><button disabled={busy} onClick={()=>void act(async()=>{await api.closeAAShare(withdrawal.share_id,"cancel",withdrawal.version);setWithdrawal(null);})} className="rounded bg-red-700 px-3 py-2 text-sm text-white">确认撤回</button></div>{error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}</div></div>}
    {workflow&&<TransferWorkflowCard workflow={workflow} onRefresh={refresh} />}{error&&!withdrawal&&<p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
  </section>;
}
