"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api/client";

type MfaStatus = Awaited<ReturnType<typeof api.mfaStatus>>;
type Enrollment = Awaited<ReturnType<typeof api.beginMfaEnrollment>>;

export function AuthenticatorSettings() {
  const [status, setStatus] = useState<MfaStatus>();
  const [enrollment, setEnrollment] = useState<Enrollment>();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const [error, setError] = useState<string>();
  useEffect(() => {
    let active = true;
    void api.mfaStatus().then(value => { if (active) setStatus(value); })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : "认证器状态读取失败，请稍后重试"); });
    return () => { active = false; };
  }, []);

  async function begin() {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError(undefined);
    try { setEnrollment(await api.beginMfaEnrollment()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "绑定准备失败，请重试"); }
    finally { pending.current = false; setBusy(false); }
  }

  async function confirm() {
    if (pending.current || !/^\d{6}$/.test(code)) return;
    pending.current = true; setBusy(true); setError(undefined);
    const verification = code; setCode("");
    try {
      setStatus(await api.confirmMfaEnrollment(verification));
      setEnrollment(undefined);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "动态码验证失败，请重试"); }
    finally { pending.current = false; setBusy(false); }
  }

  if (status?.method === "mock" || (!status && !error)) return null;
  return <section aria-label="认证器设置" className="rounded-xl border border-slate-200 bg-white p-4">
    <h3 className="font-semibold text-slate-950">认证器验证</h3>
    {status?.enrolled ? <p role="status" className="mt-2 text-sm text-emerald-700">认证器已绑定。强验证时请输入本人认证器新生成的六位动态码。</p>
      : <>
        <p className="mt-2 text-sm text-slate-600">绑定本人认证器后，可用动态码验证转账、理财和额度修改。绑定前需要近期登录。</p>
        {!enrollment ? <button disabled={busy || !status} onClick={() => void begin()} className="mt-3 rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white">{busy ? "正在准备…" : "绑定认证器"}</button>
          : <div className="mt-4 space-y-3">
            <p className="text-sm text-slate-600">在认证器中选择手动添加账户，类型选择基于时间，输入以下密钥。请仅在本人认证器中保存。</p>
            <label className="block text-sm">认证器密钥<input aria-label="认证器绑定密钥" readOnly autoComplete="off" value={enrollment.secret} className="mt-1 block w-full rounded border bg-slate-50 px-3 py-2 font-mono text-sm" /></label>
            <label className="block text-sm">当前六位动态码<input aria-label="认证器绑定动态码" type="password" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={event => setCode(event.target.value.replace(/\D/g, ""))} className="ml-3 rounded border px-3 py-2" /></label>
            <p className="text-xs text-slate-500">绑定成功后密钥会从页面清除。交易验证请使用认证器随后生成的新动态码。</p>
            <div className="flex gap-4">
              <button disabled={busy || !/^\d{6}$/.test(code)} onClick={() => void confirm()} className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white">{busy ? "正在验证…" : "确认绑定"}</button>
              <button disabled={busy} onClick={() => { setEnrollment(undefined); setCode(""); setError(undefined); }} className="text-sm underline">取消绑定</button>
            </div>
          </div>}
      </>}
    {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
  </section>;
}
