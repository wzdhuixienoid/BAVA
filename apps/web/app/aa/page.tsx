"use client";
import {useEffect,useState} from "react";
import Link from "next/link";
import {api} from "@/lib/api/client";
import {AARequestCard} from "@/features/aa/AARequestCard";
import type {AARequest} from "@/features/aa/types";
export default function AAPage(){
  const [rows,setRows]=useState<AARequest[]>([]);const [error,setError]=useState("");
  useEffect(()=>{void api.listAA().then(setRows).catch(e=>setError(String(e)));},[]);
  return <main className="min-h-screen bg-slate-50 p-8"><div className="mx-auto max-w-4xl space-y-4"><div className="flex flex-wrap items-center justify-between gap-4"><h1 className="text-xl font-bold">AA 收款与付款请求</h1><Link href="/transfers" className="shrink-0 text-sm text-cyan-700 underline">返回转账与收款</Link></div><p className="text-sm text-slate-600">在工作台输入“100 元和张三、李四 AA，我也参与”创建草稿。这里展示本站 Mock 请求和历史，每个人只能授权自己的付款。</p>{error&&<p className="text-red-700">{error}</p>}{rows.map(row=><AARequestCard key={row.request_id} requestId={row.request_id} initialRequest={row} onDeleted={id=>setRows(current=>current.filter(item=>item.request_id!==id))} />)}{rows.length===0&&<p className="text-slate-500">当前身份没有 AA 请求。</p>}</div></main>;
}
