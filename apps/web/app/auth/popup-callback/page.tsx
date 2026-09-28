"use client";

import { useEffect, useState } from "react";
import { getOidcManager } from "@/lib/auth/AuthProvider";

export default function OidcPopupCallbackPage() {
  const [error, setError] = useState<string>();
  useEffect(() => {
    getOidcManager()
      .signinPopupCallback()
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "OIDC 登录回调失败");
      });
  }, []);
  return <main className="p-6 text-sm">{error ?? "正在完成登录…"}</main>;
}
