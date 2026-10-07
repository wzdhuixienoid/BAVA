"use client";
import { useState } from "react";
import type { components } from "@banking/api-client";
import { api } from "@/lib/api/client";

type Workflow = components["schemas"]["Workflow"];
export function ReauthenticationForm({ workflow, busy, act }: {
  workflow: Workflow; busy: boolean; act: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const [code, setCode] = useState("");
  async function verify() {
    const value = code; setCode("");
    await act(() => api.verifyTransferReauthentication(workflow.workflow_id, workflow.reauth_summary!.reauth_id, value, workflow.version));
  }
  return <div className="mt-3 rounded-lg border border-blue-200 bg-white p-3">
    <p className="text-sm font-semibold text-blue-900">需要完成强身份验证（模拟）后才能继续</p>
    {workflow.reauth_summary?.status === "PENDING" ? <div className="mt-3">
      <label htmlFor={`reauth-${workflow.workflow_id}`} className="text-xs font-semibold">身份验证码</label>
      <div className="mt-2 flex gap-2"><input id={`reauth-${workflow.workflow_id}`} type="password" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} placeholder="输入验证码" className="min-w-0 flex-1 rounded border px-2 py-1.5" /><button disabled={busy || !code} onClick={() => void verify()} className="rounded bg-blue-700 px-3 py-2 text-xs text-white">验证</button></div>
    </div> : <button disabled={busy} onClick={() => void act(() => api.startTransferReauthentication(workflow.workflow_id, workflow.version))} className="mt-3 rounded bg-blue-700 px-3 py-2 text-xs text-white">开始身份验证</button>}
  </div>;
}
