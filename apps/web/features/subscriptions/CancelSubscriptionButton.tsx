"use client";

import { useId, useRef, useState } from "react";
import type { components } from "@banking/api-client";
import { api } from "@/lib/api/client";

type Subscription = components["schemas"]["SubscriptionItem"];

export function CancelSubscriptionButton({ item, onCancelled }: {
  item: Subscription;
  onCancelled: (item: Subscription) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const requestKey = useRef<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const confirm = async () => {
    if (busy || !item.subscription_id) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.cancelSubscription(item.subscription_id, item.contract_version, requestKey.current!);
      onCancelled(result);
      dialog.current?.close();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "取消未成功，请稍后重试");
    } finally {
      setBusy(false);
    }
  };

  return <>
    <button className="mt-3 inline-block rounded border border-amber-300 px-3 py-2 text-xs font-semibold text-amber-900" onClick={() => {
      requestKey.current ??= crypto.randomUUID();
      setError(null);
      dialog.current?.showModal();
    }}>取消订阅</button>
    <dialog ref={dialog} aria-labelledby={titleId} onCancel={(event) => { if (busy) event.preventDefault(); }} className="w-[calc(100%_-_2rem)] max-w-md rounded-xl border border-slate-200 p-5 shadow-xl backdrop:bg-slate-950/40">
      <h2 id={titleId} className="text-lg font-semibold text-slate-900">确认取消订阅？</h2>
      <p className="mt-3 text-sm leading-6 text-slate-600">取消「{item.merchant}」后，将不再自动续费扣款。是否确认取消？</p>
      {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
      <div className="mt-5 flex justify-end gap-3">
        <button autoFocus disabled={busy} className="rounded-lg border border-slate-300 px-4 py-2 text-sm disabled:opacity-50" onClick={() => dialog.current?.close()}>暂不取消</button>
        <button disabled={busy} className="rounded-lg bg-red-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" onClick={() => void confirm()}>{busy ? "正在取消…" : "确认取消"}</button>
      </div>
    </dialog>
  </>;
}
