import type { components } from "@banking/api-client";
import { accountTypeLabel } from "@/lib/presentation/status";

type AccountResult = components["schemas"]["AccountListResult"] | components["schemas"]["AccountBalanceResult"];

/** Render critical facts verbatim from bank results, independently of assistant prose. */
export function AccountResults({ results }: { results: AccountResult[] }) {
  return <div aria-label="账户查询结果" className="grid min-w-0 gap-3 sm:grid-cols-2">
    {results.map((result, index) => result.kind === "ACCOUNT_BALANCE" ? (
      <section key={index} aria-label={`${result.display_name}余额`} className="min-w-0 rounded-xl border border-slate-200 bg-slate-50 p-4">
        <p className="font-semibold">{result.display_name}</p>
        <p className="mt-1 text-xs text-slate-500">{result.masked_number} · {accountTypeLabel(result.account_type)} · {result.currency}</p>
        <p className="mt-3 text-xs text-slate-500">余额</p>
        <p className="text-xl font-semibold tabular-nums">{result.balance_display}</p>
        <p className="mt-2 text-xs text-slate-500">查询时间：<time dateTime={result.as_of}>{result.as_of}</time></p>
      </section>
    ) : (
      <section key={index} aria-label="账户列表" className="min-w-0 rounded-xl border border-slate-200 p-4">
        <p className="mb-2 font-semibold">账户列表</p>
        {result.accounts.map((account) => <p key={account.account_id} className="text-sm">
          {account.display_name} · {account.masked_number} · {account.currency}
        </p>)}
        {result.accounts.length === 0 && <p className="text-sm text-slate-500">暂无可见账户</p>}
      </section>
    ))}
  </div>;
}
