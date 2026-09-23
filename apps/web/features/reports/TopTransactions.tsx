import type { components } from "@banking/api-client";
import { categoryLabel, dateLabel } from "./presentation";

type Transaction = components["schemas"]["ReportTopTransaction"];

export function TopTransactions({ transactions }: { transactions: Transaction[] }) {
  return (
    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="px-6 py-5">
        <h2 className="text-lg font-semibold text-slate-950">主要交易</h2>
        <p className="mt-1 text-sm text-slate-500">仅展示快照中已限定的主要消费。</p>
      </div>
      {transactions.length === 0 ? (
        <p className="border-t border-slate-100 px-6 py-8 text-sm text-slate-400">暂无主要交易数据。</p>
      ) : (
        <div className="overflow-x-auto border-t border-slate-100">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500">
              <tr>
                <th className="px-6 py-3 font-medium">日期</th>
                <th className="px-4 py-3 font-medium">商户 / 描述</th>
                <th className="px-4 py-3 font-medium">分类</th>
                <th className="px-4 py-3 font-medium">账户</th>
                <th className="px-6 py-3 text-right font-medium">金额</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {transactions.map((item) => (
                <tr key={item.transaction_id}>
                  <td className="whitespace-nowrap px-6 py-4 text-slate-500">{dateLabel(item.occurred_at)}</td>
                  <td className="px-4 py-4">
                    <p className="font-medium text-slate-900">{item.merchant}</p>
                    <p className="mt-0.5 text-xs text-slate-400">{item.description}</p>
                  </td>
                  <td className="px-4 py-4 text-slate-600">{categoryLabel(item.category)}</td>
                  <td className="px-4 py-4 font-mono text-xs text-slate-500">{item.account_id}</td>
                  <td className="whitespace-nowrap px-6 py-4 text-right font-semibold text-slate-950">
                    {item.amount_display}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
