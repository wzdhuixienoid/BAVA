"use client";

import { useEffect, useRef, useState } from "react";
import type { components } from "@banking/api-client";
import { categoryLabel, dateTimeLabel } from "@/features/reports/presentation";
import { api } from "@/lib/api/client";

type Transaction = components["schemas"]["DashboardTransaction"];
type TransactionPage = components["schemas"]["DashboardTransactionPage"];

export function RecentTransactions({ transactions, accountNames, refreshKey, onAvailableMonths }: { transactions: Transaction[]; accountNames: Record<string, string>; refreshKey?: string; onAvailableMonths?: (months: string[]) => void }) {
  const [year, setYear] = useState("");
  const [month, setMonth] = useState("");
  const [category, setCategory] = useState("");
  const [account, setAccount] = useState("");
  const [page, setPage] = useState<TransactionPage>({
    transactions, total_count: transactions.length, offset: 0,
    available_months: [...new Set(transactions.map(item => dateTimeLabel(item.occurred_at).slice(0, 7)))].sort().reverse(),
    available_categories: [...new Set(transactions.map(item => item.category))].sort(),
  });
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [moreError, setMoreError] = useState("");
  const [retry, setRetry] = useState(0);
  const requestVersion = useRef(0);
  const morePending = useRef(false);
  const scroller = useRef<HTMLDivElement>(null);
  const filtered = !!(year || month || category || account);
  const rows = loading || error ? [] : page.transactions;

  useEffect(() => {
    const version = ++requestVersion.current;
    setLoading(true); setError(""); setMoreError(""); setLoadingMore(false); morePending.current = false;
    void api.getDashboardTransactions({ year, month_number: month, category, account_id: account }).then(next => {
      if (version !== requestVersion.current) return;
      setPage(next);
      onAvailableMonths?.(next.available_months);
      if (scroller.current) scroller.current.scrollTop = 0;
    }).catch(reason => {
      if (version === requestVersion.current) setError(reason instanceof Error ? reason.message : "消费明细加载失败，请重试。");
    }).finally(() => {
      if (version === requestVersion.current) setLoading(false);
    });
    return () => { requestVersion.current += 1; };
  }, [year, month, category, account, refreshKey, retry, onAvailableMonths]);

  async function loadMore() {
    if (loading || morePending.current || page.transactions.length >= page.total_count) return;
    const version = requestVersion.current;
    morePending.current = true; setLoadingMore(true); setMoreError("");
    try {
      const next = await api.getDashboardTransactions({ year, month_number: month, category, account_id: account, offset: page.transactions.length });
      if (version === requestVersion.current) setPage(current => ({ ...next, transactions: [...current.transactions, ...next.transactions] }));
    } catch (reason) {
      if (version === requestVersion.current) setMoreError(reason instanceof Error ? reason.message : "更多消费加载失败，请重试。");
    } finally {
      if (version === requestVersion.current) { morePending.current = false; setLoadingMore(false); }
    }
  }

  return <section aria-label="消费明细" className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-6 py-5">
      <div><h2 className="text-lg font-semibold text-slate-950">消费明细</h2><p className="mt-1 text-sm text-slate-500">按时间倒序展示消费，可筛选年月、类别和账户，下滑查看更多。</p></div>
      {filtered && <button className="rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-700 hover:bg-slate-50" onClick={() => { setYear(""); setMonth(""); setCategory(""); setAccount(""); }}>清除筛选</button>}
    </div>
      <div ref={scroller} role="region" aria-label="消费明细列表" aria-busy={loading} tabIndex={0} className="max-h-[24.5rem] overflow-auto overscroll-contain focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-600">
        <table aria-label="消费明细表" className="w-full min-w-[840px] table-fixed text-left text-sm">
          <thead className="sticky top-0 z-10 h-[4.5rem] bg-slate-50 text-xs text-slate-500">
            <tr>
              <th scope="col" className="w-[28%] px-6 py-2 font-medium"><span className="block">时间</span><div className="mt-1 flex gap-2"><select aria-label="筛选消费年份" value={year} onChange={event => setYear(event.target.value)} className="h-7 min-w-0 flex-1 rounded border border-slate-200 bg-white px-2 text-xs font-normal text-slate-700"><option value="">全部年份</option>{[...new Set(page.available_months.map(value => value.slice(0, 4)))].map(value => <option key={value} value={value}>{value}年</option>)}</select><select aria-label="筛选消费月份" value={month} onChange={event => setMonth(event.target.value)} className="h-7 w-20 rounded border border-slate-200 bg-white px-2 text-xs font-normal text-slate-700"><option value="">全部月份</option>{Array.from({length:12}, (_, index) => <option key={index + 1} value={String(index + 1)}>{index + 1}月</option>)}</select></div></th>
              <th scope="col" className="w-[24%] px-4 font-medium">商户 / 描述</th>
              <th scope="col" className="w-[14%] px-4 py-2 font-medium"><label className="block">分类<select aria-label="筛选消费类别" value={category} onChange={event => setCategory(event.target.value)} className="mt-1 block h-7 w-full rounded border border-slate-200 bg-white px-2 text-xs font-normal text-slate-700"><option value="">全部类别</option>{page.available_categories.map(value => <option key={value} value={value}>{categoryLabel(value)}</option>)}</select></label></th>
              <th scope="col" className="w-[16%] px-4 py-2 font-medium"><label className="block">账户<select aria-label="筛选消费账户" value={account} onChange={event => setAccount(event.target.value)} className="mt-1 block h-7 w-full rounded border border-slate-200 bg-white px-2 text-xs font-normal text-slate-700"><option value="">全部账户</option>{Object.entries(accountNames).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label></th>
              <th scope="col" className="w-[18%] px-6 text-right font-medium">金额</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map(item => <tr key={item.transaction_id} className="h-16">
              <td className="whitespace-nowrap px-6 py-2 text-slate-500"><time dateTime={item.occurred_at}>{dateTimeLabel(item.occurred_at)}</time></td>
              <td className="px-4 py-2"><p className="truncate font-medium text-slate-900" title={item.merchant}>{item.merchant}</p><p className="mt-0.5 truncate text-xs text-slate-400" title={item.description}>{item.description}</p></td>
              <td className="px-4 py-2 text-slate-600">{categoryLabel(item.category)}</td>
              <td className="whitespace-nowrap px-4 py-2 text-slate-600">{accountNames[item.account_id] ?? "账户"}</td>
              <td className="whitespace-nowrap px-6 py-2 text-right font-semibold tabular-nums text-slate-950">{item.amount_display}<span className="ml-1 text-xs font-normal text-slate-400">{item.currency}</span></td>
            </tr>)}
            {rows.length === 0 && <tr><td colSpan={5} className="px-6 py-8 text-sm text-slate-500">{loading ? "正在查询消费明细…" : error ? <div role="alert">{error} <button className="ml-2 text-cyan-700 underline" onClick={() => setRetry(value => value + 1)}>重试</button></div> : filtered ? "没有符合筛选条件的消费记录。" : "暂无消费记录。"}</td></tr>}
          </tbody>
        </table>
        {!loading && !error && rows.length < page.total_count && <div className="border-t border-slate-100 p-3 text-center text-xs">{moreError && <p role="alert" className="mb-2 text-red-700">{moreError}</p>}<button disabled={loadingMore} className="rounded-lg border px-4 py-2 text-slate-600 hover:bg-slate-50 disabled:opacity-50" onClick={() => void loadMore()}>{loadingMore ? "正在加载…" : "加载更多消费"}</button></div>}
      </div>
  </section>;
}
