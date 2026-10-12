"use client";
import {useRef,useState} from "react";
import type {components} from "@banking/api-client";
import {api} from "@/lib/api/client";
type Evidence = components["schemas"]["WealthEvidence"];
const sourceLabels:Record<string,string>={REGULATION:"监管规章",BANK_EDUCATION:"银行投教",GOVERNMENT_EDUCATION:"政府投教",MANAGER_EDUCATION:"管理人投教",MOCK_PRODUCT:"模拟产品条款",MOCK_DESIGN:"模拟设计画像"};
const officialHosts = new Set(["www.hunan.gov.cn", "dfjrjgj.hunan.gov.cn", "www.boc.cn", "www.bocim.com"]);
export function safeEvidenceSource(source: Evidence): boolean {
  if(source.scope === "DESIGN") return /^\/api\/v1\/wealth\/product-profiles\/mock-wealth-\d{2}\/mock-design-v\d+$/.test(source.url);
  if(source.scope === "PRODUCT") return /^\/api\/v1\/wealth\/documents\/[a-zA-Z0-9:_-]+$/.test(source.url) && source.url === `/api/v1/wealth/documents/${source.document_id}`;
  try {const url=new URL(source.url);return ["http:","https:"].includes(url.protocol) && officialHosts.has(url.hostname) && !url.username && !url.password;} catch {return false;}
}

export function WealthEvidencePanel({evidence}: {evidence: Evidence[]}) {
  const [selected,setSelected]=useState<Evidence|null>(null);
  const [content,setContent]=useState("");const [error,setError]=useState("");
  const pending=useRef(false);
  async function open(source:Evidence) {
    if(pending.current || !safeEvidenceSource(source))return;
    pending.current=true;setError("");
    try {const doc=source.scope === "PRODUCT" ? await api.wealthDocument(source.document_id!) : null;
      setContent(doc?.content ?? source.content);setSelected(source);
    } catch {setError("资料暂时无法打开，请重试；已保存的分析仍可查看。");} finally {pending.current=false;}
  }
  return <div className="mt-3"><details><summary className="cursor-pointer text-sm text-cyan-800">查看依据</summary><div className="mt-2 space-y-2">{evidence.map(e=><div key={e.evidence_id} className="text-xs"><button disabled={!safeEvidenceSource(e)} onClick={()=>void open(e)} className="text-cyan-800 underline">{e.scope === "PRODUCT" ? "模拟产品资料" : e.scope === "DESIGN" ? "模拟设计画像" : "通用教育知识"} · {e.title}</button><p className="text-slate-500">{sourceLabels[e.source_type] ?? "资料"} · {e.source_name} · 版本 {e.version}{e.verified_at ? ` · 核验于 ${e.verified_at}` : ""}</p></div>)}</div></details>
    {error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
    {selected && <div role="dialog" aria-label="分析依据" className="fixed inset-8 z-50 overflow-auto rounded-xl border bg-white p-6 shadow-xl sm:inset-x-1/4"><button onClick={()=>setSelected(null)} className="float-right rounded border px-3 py-1">关闭依据</button><h3 className="font-semibold">{selected.title}</h3><p className="mt-4 whitespace-pre-wrap text-sm leading-7">{content}</p><p className="mt-3 text-xs text-slate-500">{sourceLabels[selected.source_type] ?? "资料"} · {selected.source_name} · 版本 {selected.version}{selected.verified_at ? ` · 核验于 ${selected.verified_at}` : ""}</p>{selected.scope === "EDUCATION" && safeEvidenceSource(selected) && <a className="mt-3 block text-sm text-cyan-700 underline" href={selected.url} target="_blank" rel="noopener noreferrer">打开官方原文</a>}<p className="mt-2 text-xs text-slate-500">{selected.scope === "EDUCATION" ? "通用知识只解释概念，不证明模拟产品的具体条款。" : selected.scope === "DESIGN" ? "模拟画像不是实际持仓或组合回测，不改变原交易条款。" : "具体交易按绑定条款、重新核对及授权办理。"}</p></div>}
  </div>;
}

