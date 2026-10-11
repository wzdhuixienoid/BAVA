"use client";
import {useRef, useState} from "react";
import type {components} from "@banking/api-client";
import {api} from "@/lib/api/client";

type Product = components["schemas"]["WealthProductResult"];
type Account = components["schemas"]["AccountBalanceResult"];

/** Interest opens an editor; only explicit filled submission creates a review draft. */
export function WealthPurchaseEntry({product,allowed,creationKey,conversationId,accounts,amount,accountId,onRefresh,loadAccounts}: {
  product:Product; allowed:boolean; creationKey?:string|null; conversationId?:string;
  accounts?:Account[]; amount?:string|null; accountId?:string|null; onRefresh?:()=>Promise<void>; loadAccounts?:()=>Promise<Account[]>;
}) {
  const [open,setOpen]=useState(false), [available,setAvailable]=useState<Account[]>(accounts ?? []);
  const [quantity,setQuantity]=useState(amount ?? ""), [account,setAccount]=useState(accountId ?? "");
  const [error,setError]=useState(""), [busy,setBusy]=useState(false), [created,setCreated]=useState<string|null>(null);
  const pending=useRef(false), key=useRef<string|null>(creationKey ?? null);
  async function begin() {
    if(pending.current)return;
    setOpen(true);setError("");
    if(accounts){setAvailable(accounts);return;}
    pending.current=true;setBusy(true);
    try {setAvailable(await (loadAccounts?.() ?? api.wealthAccounts()));} catch {setError("账户暂时无法加载，请再次点击购买入口重试。");}
    finally {pending.current=false;setBusy(false);}
  }
  async function review() {
    if(pending.current || created || !account || !quantity.trim() || !allowed || !product.purchase_allowed)return;
    pending.current=true;setBusy(true);setError("");
    key.current ??= crypto.randomUUID();
    try {
      const workflow=await api.wealthCreate({direction:"PURCHASE",redeem_all:false,product_id:product.product_id,account_id:account,quantity:quantity.trim(),creation_key:key.current,conversation_id:conversationId});
      setCreated(workflow.conversation_id);
      await onRefresh?.();
    } catch(e) {setError(e instanceof Error ? e.message : "暂时无法创建核对，请重试。");}
    finally {pending.current=false;setBusy(false);}
  }
  const enabled=allowed && product.purchase_allowed;
  return <div className="mt-3 border-t pt-3">
    {created ? <a href={`/?conversation=${created}`} className="text-cyan-800 underline">查看申购申请</a> : <>
      <button disabled={!enabled || busy} onClick={()=>void begin()} className="rounded bg-cyan-700 px-4 py-2 text-white">购买{product.name}</button>
      {!enabled && <p className="mt-1 text-xs text-amber-900">{!allowed ? "已暂停新理财交易" : product.purchase_block_reason ?? "暂不能购买"}</p>}
      {open && enabled && <div className="mt-3 space-y-3">
        <label className="block text-sm">本人付款账户<select aria-label={`购买${product.name}的账户`} value={account} onChange={e=>setAccount(e.target.value)} className="ml-2 rounded border p-2"><option value="">请选择账户</option>{available.map(a=><option key={a.account_id} value={a.account_id}>{a.display_name} · {a.balance_display}</option>)}</select></label>
        <label className="block text-sm">申购金额（元）<input aria-label={`购买${product.name}的金额`} inputMode="decimal" value={quantity} onChange={e=>setQuantity(e.target.value)} className="ml-2 rounded border p-2"/></label>
        <p className="text-xs text-slate-600">{product.minimum_display}起购。确认提交前不会扣款。</p>
        <button disabled={busy || !account || !quantity.trim()} onClick={()=>void review()} className="rounded border px-3 py-2 text-cyan-800">下一步：核对申购</button>
      </div>}
    </>}
    {error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
  </div>;
}
