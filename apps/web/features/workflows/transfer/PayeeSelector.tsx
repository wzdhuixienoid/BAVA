"use client";

import Link from "next/link";
import { useState } from "react";
import type { components } from "@banking/api-client";
import { api } from "@/lib/api/client";

type Workflow = components["schemas"]["Workflow"];
type Payee = components["schemas"]["PayeeSummary"];

export function PayeeSelector({ workflow, busy, act }: {
  workflow: Workflow;
  busy: boolean;
  act: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("");
  const [showExisting, setShowExisting] = useState(false);
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<Payee[]>([]);
  const [error, setError] = useState<string | null>(null);
  const state = (workflow.presentation?.transfer_state ?? workflow.state) as components["schemas"]["TransferWorkflowState"];

  async function loadExisting() {
    setShowExisting(true); setLoading(true); setError(null);
    try {
      const all: Payee[] = [];
      for (let offset = 0; ; offset += 100) {
        const page = await api.listPayees(undefined, offset);
        all.push(...page);
        if (page.length < 100) break;
      }
      setItems(all);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "无法读取收款人，请重试"); }
    finally { setLoading(false); }
  }

  const normalized = filter.trim().toLocaleLowerCase();
  const choices = (showExisting ? items : workflow.presentation?.payee_options ?? []).filter((item) =>
    [item.display_name, item.bank_name, item.masked_account, item.phone_alias].some((value) => value?.toLocaleLowerCase().includes(normalized)),
  );
  const addHref = `/payees?conversation=${encodeURIComponent(workflow.conversation_id)}&workflow=${encodeURIComponent(workflow.workflow_id)}`;

  return <section aria-label="收款人确认" className="mt-3 rounded-lg border border-amber-200 bg-white p-3">
    <h3 className="text-sm font-semibold">收款人确认</h3>
    {state.required_input?.message && <p className="mt-2 text-xs text-slate-600">{state.required_input.message}</p>}
    <div className="mt-3 flex flex-wrap gap-2">
      <button disabled={busy || loading} onClick={() => void loadExisting()} className="rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">选择已有收款人</button>
      <Link href={addHref} className="rounded-lg border border-cyan-700 px-3 py-2 text-xs font-semibold text-cyan-800">新增收款人</Link>
    </div>
    <p className="mt-2 text-[11px] text-slate-500">新增后可返回这笔转账，选择保存的收款人继续。</p>
    {showExisting && <label className="mt-3 block text-xs text-slate-600">搜索已有收款人<input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="姓名、银行、尾号或别名" className="mt-1 w-full rounded border px-2 py-1.5 text-sm" /></label>}
    {loading && <p role="status" className="mt-3 text-xs">正在读取收款人…</p>}
    {error && <p role="alert" className="mt-3 text-xs text-red-700">{error}</p>}
    <div aria-label="已有收款人" className="mt-3 grid max-h-64 gap-2 overflow-y-auto sm:grid-cols-2">
      {choices.map((item) => <button key={item.payee_id} disabled={busy || loading} aria-label={`选择${item.display_name}，${item.bank_name}，${item.masked_account}${item.phone_alias ? `，${item.phone_alias}` : ""}`} onClick={() => void act(() => api.selectPayee(workflow.workflow_id, item.payee_id, workflow.version, item.display_name))} className="rounded-lg border border-slate-200 p-3 text-left hover:border-cyan-600 hover:bg-cyan-50 disabled:opacity-50">
        <span className="block text-sm font-semibold">{item.display_name}</span><span className="mt-1 block text-xs text-slate-600">{item.bank_name} · {item.masked_account}</span>{item.phone_alias && <span className="mt-1 block text-xs text-slate-500">{item.phone_alias}</span>}
      </button>)}
      {showExisting && !loading && !error && choices.length === 0 && <p className="text-xs text-slate-500">未找到收款人，可以使用新增入口。</p>}
    </div>
    <div className="mt-3 flex gap-2">
      <input aria-label="收款人姓名或别名" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="也可输入姓名或别名查找" className="min-w-0 flex-1 rounded border px-2 py-1.5 text-sm" />
      <button disabled={busy || !query.trim()} onClick={() => void act(() => api.setRecipientQuery(workflow.workflow_id, query.trim(), workflow.version))} className="rounded border px-3 py-1.5 text-xs font-semibold disabled:opacity-50">查找</button>
    </div>
  </section>;
}
