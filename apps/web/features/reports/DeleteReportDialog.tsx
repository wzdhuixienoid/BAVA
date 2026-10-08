"use client";

import { useEffect, useRef } from "react";

export function DeleteReportDialog({ title, busy, error, onCancel, onConfirm }: {
  title: string;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} onCancel={(event) => { event.preventDefault(); if (!busy) onCancel(); }}
    aria-labelledby="delete-report-title" aria-describedby="delete-report-description"
    className="w-[calc(100%_-_2rem)] max-w-md rounded-2xl bg-white p-6 shadow-xl backdrop:bg-slate-950/30">
    <h2 id="delete-report-title" className="text-lg font-semibold text-slate-950">删除报告？</h2>
    <p className="mt-3 text-sm font-medium text-slate-700">{title}</p>
    <p id="delete-report-description" className="mt-2 text-sm leading-6 text-slate-500">删除后，该报告将从历史报告和对话入口中隐藏。你可以在“已删除”中恢复。</p>
    {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
    <div className="mt-6 flex justify-end gap-3">
      <button autoFocus disabled={busy} onClick={onCancel} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 disabled:opacity-50">取消</button>
      <button disabled={busy} onClick={onConfirm} className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50">{busy ? "正在删除…" : "删除报告"}</button>
    </div>
  </dialog>;
}
