import type { components } from "@banking/api-client";
import { queryTime } from "@/lib/presentation/time";
import { MarkdownMessage } from "@/features/conversation/MarkdownMessage";

type Statement = components["schemas"]["AccountStatementResult"];

export function StatementAnswer({ results }: { results: Statement[] }) {
  return <div aria-label="账单查询回复" className="space-y-5">
    {results.map((page, index) => page.summary && page.answer ? <MarkdownMessage key={index} content={page.answer} /> : <div key={index} className="space-y-3">
      <p className="text-xs text-slate-500">{queryTime(page.start_at)} 至 {queryTime(page.end_at)}（北京时间，终点不含）</p>
      {page.total_count > page.transactions.length && <p className="text-xs text-slate-500">这条历史结果只有部分明细，重新查询可查看完整总额与收款人汇总。</p>}
      {page.transactions.length ? <ul className="divide-y divide-slate-100">
        {page.transactions.map((row) => <li key={row.transaction_id} className="py-3 first:pt-0">
          <div className="flex flex-wrap justify-between gap-2">
            <span className="font-medium">{row.merchant}</span>
            <span className="font-semibold tabular-nums">{row.amount_display} <span className="text-xs font-normal text-slate-500">{row.currency}</span></span>
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-500">{row.occurred_at_display} · {row.account_display} · {row.category_display} · {row.direction === "DEBIT" ? "支出" : "收入"} · 已入账</p>
          {row.description && <p className="mt-1 text-xs text-slate-500">{row.description}</p>}
        </li>)}
      </ul> : <p>{page.total_count === 0 ? "所选期间和筛选条件下没有已入账记录。" : "已到最后一页，没有更多记录。"}</p>}
      {page.next_offset !== null && <p className="text-xs text-slate-500">当前展示第 {page.offset + 1}–{page.offset + page.transactions.length} 条，共 {page.total_count} 条。输入“下一页”可继续查询。</p>}
      <p className="text-xs leading-5 text-slate-500">{page.posting_scope}</p>
    </div>)}
  </div>;
}
