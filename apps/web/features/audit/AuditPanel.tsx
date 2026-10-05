"use client";

import { useEffect, useState } from "react";
import type { components } from "@banking/api-client";
import { api } from "@/lib/api/client";
import { AuditTimeline, AuditUnavailable } from "./AuditTimeline";

export function AuditPanel({ taskId, revision }: { taskId: string; revision: number }) {
  const [open, setOpen] = useState(false);
  const [trace, setTrace] = useState<components["schemas"]["AuditTrace"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    if (!open) return;
    let active = true;
    setTrace(null); setError(null);
    api.getTaskAudit(taskId).then((result) => { if (active) setTrace(result); })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : "无法读取审计资源"); });
    return () => { active = false; };
  }, [open, taskId, revision, reload]);
  return <div className="my-3 min-w-0">
    <button className="rounded border border-slate-200 px-3 py-2 text-xs font-semibold text-cyan-800" onClick={() => setOpen(!open)}>{open ? "收起审计链" : "查看审计链"}</button>
    {open && <div className="mt-2 space-y-2"><button className="text-xs text-cyan-800" onClick={() => setReload(reload + 1)}>刷新审计事实</button>
      {error ? <AuditUnavailable message={error} /> : trace ? <AuditTimeline trace={trace} /> : <p className="text-xs text-slate-500">正在读取持久审计事实…</p>}
    </div>}
  </div>;
}
