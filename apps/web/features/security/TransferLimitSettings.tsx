"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";

type Preference = Awaited<ReturnType<typeof api.transferPreference>>;

export function TransferLimitSettings({ onSaved, embedded = false }: {
  onSaved?: () => Promise<void>;
  embedded?: boolean;
}) {
  const [preference, setPreference] = useState<Preference>();
  const [amount, setAmount] = useState("");
  const [review, setReview] = useState<string>();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  useEffect(() => {
    void api.transferPreference().then(value => {
      setPreference(value); setAmount(value.passwordless_limit);
    }).catch(reason => setError(reason instanceof Error ? reason.message : "额度读取失败"));
  }, []);
  async function save() {
    if (review === undefined || !preference) return;
    setBusy(true); setError(undefined);
    const verification = code; setCode("");
    try {
      const updated = await api.saveTransferPreference(review, preference.version, verification);
      setPreference(updated); setAmount(updated.passwordless_limit); setReview(undefined);
      await onSaved?.();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "额度保存失败"); }
    finally { setBusy(false); }
  }
  const valid = /^\d+(?:\.\d{1,2})?$/.test(amount) && Number(amount) >= 0 && Number(amount) <= 200;
  return <section className={embedded ? "min-w-0" : "rounded-xl border bg-white p-5"} aria-label="免密支付额度设置">
    {!embedded && <h2 className="font-semibold">免密支付额度</h2>}
    <p className={`${embedded ? "" : "mt-2 "}text-sm text-slate-600`}>最高可设置200元，设为0可关闭免密。只有单笔金额严格小于此额度、且含本笔的当日累计不超过1000元时，确认后可免强验证；其他转账需要强验证。</p>
    {preference && <p className="mt-3 text-sm">当前额度：<strong>{preference.passwordless_limit_display}</strong></p>}
    {review === undefined ? <>
      <label className="mt-3 block text-sm">新额度（元）<input aria-label="新免密额度" type="number" min="0" max="200" step="0.01" value={amount} onChange={event => setAmount(event.target.value)} className="ml-3 rounded border px-2 py-1" /></label>
      <button disabled={!preference || !valid || busy} onClick={() => { setError(undefined); setReview(amount); }} className="mt-3 rounded bg-slate-900 px-4 py-2 text-sm text-white">核对额度设置</button>
    </> : <div className="mt-4 rounded border border-amber-200 bg-amber-50 p-4">
      <p className="text-sm">确认将本人免密支付额度设置为 <strong>{review} 元</strong>？修改额度本身需要强验证，不能使用免密额度授权。</p>
      <label className="mt-3 block text-sm">身份验证码<input aria-label="额度设置验证码" type="password" autoComplete="one-time-code" value={code} onChange={event => setCode(event.target.value)} className="ml-3 rounded border px-2 py-1" /></label>
      <button disabled={busy || !code} onClick={() => void save()} className="mt-3 rounded bg-blue-700 px-4 py-2 text-sm text-white">确认并验证</button>
      <button disabled={busy} onClick={() => { setReview(undefined); setCode(""); }} className="ml-3 text-sm underline">返回修改</button>
    </div>}
    {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
  </section>;
}
