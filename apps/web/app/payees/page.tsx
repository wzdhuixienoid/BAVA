"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import type { components } from "@banking/api-client";
import { api } from "@/lib/api/client";

type Payee = components["schemas"]["PayeeSummary"];
const banks = ["星河银行（虚构）", "蓝海银行（虚构）", "森林银行（虚构）", "远山银行（虚构）"];

export default function PayeesPage() {
  const [items, setItems] = useState<Payee[]>([]);
  const [name, setName] = useState("");
  const [bank, setBank] = useState(banks[0]);
  const [suffix, setSuffix] = useState("");
  const [alias, setAlias] = useState("");
  const [reviewing, setReviewing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [returnHref, setReturnHref] = useState("/");
  const [returnToTransfer, setReturnToTransfer] = useState(false);
  const refresh = useCallback(async () => {
    const all: Payee[] = [];
    for (let offset = 0; ; offset += 100) {
      const page = await api.listPayees(undefined, offset);
      all.push(...page);
      if (page.length < 100) break;
    }
    setItems(all);
  }, []);
  useEffect(() => { void refresh().catch((reason: Error) => setError(reason.message)); }, [refresh]);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const conversation = params.get("conversation");
    if (conversation) setReturnHref(`/?conversation=${encodeURIComponent(conversation)}`);
    setReturnToTransfer(params.has("workflow"));
  }, []);

  function review(event: FormEvent) {
    event.preventDefault(); setReviewing(true); setError(null); setNotice("");
  }
  async function save() {
    setBusy(true); setError(null);
    try {
      await api.createPayee({ display_name: name.trim(), bank_name: bank, account_suffix: suffix, phone_alias: alias.trim(), confirmed: true });
      setReviewing(false); setName(""); setSuffix(""); setAlias(""); setNotice("收款人已保存，可以在对话中查询并发起转账。");
      await refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "保存失败，请重试"); }
    finally { setBusy(false); }
  }
  const input = "mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2";
  return <main className="min-h-screen bg-slate-50 px-5 py-10"><div className="mx-auto max-w-5xl">
    <header className="mb-7 flex items-center justify-between gap-4"><h1 className="text-2xl font-semibold">收款人管理</h1><Link href={returnHref} className="text-sm text-cyan-700 underline">{returnToTransfer ? "返回转账" : "返回工作台"}</Link></header>
    {error && <p role="alert" className="mb-4 rounded bg-red-50 p-3 text-red-800">{error}</p>}
    {notice && <p role="status" className="mb-4 rounded bg-emerald-50 p-3 text-emerald-800">{notice}{returnToTransfer && <Link href={returnHref} className="ml-3 underline">返回转账选择收款人</Link>}</p>}
    <section className="mb-8 rounded-xl border bg-white p-5">
      <h2 className="font-semibold">新增收款人</h2><p className="mt-2 text-sm text-slate-500">使用模拟账户资料。保存需要核对确认，每笔转账仍需强身份验证。</p>
      {!reviewing ? <form onSubmit={review} className="mt-4 grid gap-4 sm:grid-cols-2">
        <label className="text-sm">收款人姓名<input required maxLength={100} className={input} value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label className="text-sm">收款银行<select className={input} value={bank} onChange={(e) => setBank(e.target.value)}>{banks.map((value) => <option key={value}>{value}</option>)}</select></label>
        <label className="text-sm">账户尾号（模拟）<input required inputMode="numeric" pattern="[0-9]{4}" maxLength={4} className={input} value={suffix} onChange={(e) => setSuffix(e.target.value)} /></label>
        <label className="text-sm">别名（选填）<input maxLength={100} className={input} value={alias} onChange={(e) => setAlias(e.target.value)} /></label>
        <button className="rounded-lg bg-slate-900 px-4 py-2 text-white sm:col-span-2">核对收款人资料</button>
      </form> : <div className="mt-4 rounded-lg bg-amber-50 p-4">
        <p className="text-sm font-semibold text-amber-800">YELLOW · 黄色 · 请确认收款资料</p><p className="mt-2">{name} · {bank} · ****{suffix}{alias && ` · ${alias}`}</p>
        <div className="mt-4 flex gap-3"><button disabled={busy} onClick={() => void save()} className="rounded-lg bg-amber-700 px-4 py-2 text-white">{busy ? "保存中…" : "确认保存"}</button><button disabled={busy} onClick={() => setReviewing(false)} className="rounded-lg border px-4 py-2">返回修改</button></div>
      </div>}
    </section>
    <h2 className="mb-3 font-semibold">可转账收款人</h2><div className="grid gap-3 sm:grid-cols-2">{items.map((item) => <article key={item.payee_id} className="rounded-lg border bg-white p-4"><p className="font-semibold">{item.display_name}</p><p className="mt-2 text-sm text-slate-600">{item.bank_name} · {item.masked_account}</p>{item.phone_alias && <p className="mt-1 text-xs text-slate-500">{item.phone_alias}</p>}</article>)}</div>
  </div></main>;
}
