"use client";
import {useEffect,useState} from "react";
import Link from "next/link";
import {api} from "@/lib/api/client";
import {AARequestCard} from "@/features/aa/AARequestCard";
import type {AARequest} from "@/features/aa/types";
export default function AAPage(){
  const [rows,setRows]=useState<AARequest[]>([]);const [sessions,setSessions]=useState<Awaited<ReturnType<typeof api.mockSessions>>|null>(null);const [error,setError]=useState("");
  useEffect(()=>{void api.listAA().then(setRows).catch(e=>setError(String(e)));void api.mockSessions().then(setSessions).catch(e=>setError(String(e)));},[]);
  return <main className="min-h-screen bg-slate-50 p-8"><div className="mx-auto max-w-4xl space-y-4"><div className="flex justify-between"><h1 className="text-xl font-bold">AA 收款与付款请求</h1><Link href="/">返回工作台</Link></div><p className="text-sm text-slate-600">在工作台输入“100 元和张三、李四 AA，我也参与”创建草稿。这里展示本站 Mock 请求和历史，每个人只能授权自己的付款。</p>{sessions?.enabled&&<div className="rounded border bg-amber-50 p-3 text-sm"><p>Mock 演示登录（仅开发环境）：{sessions.identities.find(x=>x.identity===sessions.current_user_id)?.name}</p><div className="mt-2 flex gap-3">{sessions.identities.map(x=><button key={x.identity} className="rounded border bg-white px-3 py-1" onClick={()=>void api.mockLogin(x.identity).then(value=>{localStorage.setItem("banking-mock-session",value.access_token);location.reload();}).catch(e=>setError(String(e)))}>{x.name}</button>)}</div></div>}{error&&<p className="text-red-700">{error}</p>}{rows.map(row=><AARequestCard key={row.request_id} requestId={row.request_id} />)}{rows.length===0&&<p className="text-slate-500">当前身份没有 AA 请求。</p>}</div></main>;
}
