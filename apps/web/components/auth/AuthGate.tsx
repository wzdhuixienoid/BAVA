"use client";

import { useAuth } from "@/lib/auth/AuthProvider";
import { usePathname } from "next/navigation";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const auth = useAuth();
  const pathname = usePathname();
  if (pathname === "/auth/popup-callback") return children;
  if (!auth.ready) {
    return <main className="grid min-h-screen place-items-center">正在检查认证状态…</main>;
  }
  if (auth.error) {
    return <main className="grid min-h-screen place-items-center text-red-700">{auth.error}</main>;
  }
  if (!auth.authenticated) {
    return (
      <main className="grid min-h-screen place-items-center bg-slate-50 p-6">
        <section className="rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm">
          <h1 className="text-2xl font-semibold">登录 BAVA</h1>
          <p className="mt-2 text-sm text-slate-500">使用组织的身份提供商安全登录。</p>
          <button
            className="mt-6 rounded-lg bg-cyan-500 px-5 py-2.5 font-semibold text-slate-950"
            onClick={() => void auth.login()}
          >
            登录
          </button>
        </section>
      </main>
    );
  }
  return children;
}
