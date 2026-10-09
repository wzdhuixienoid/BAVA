import type { components } from "@banking/api-client";
import { queryTime } from "@/lib/presentation/time";

type AccountResult = components["schemas"]["AccountListResult"] | components["schemas"]["AccountBalanceResult"];

/** A single assistant answer grounded in bank results, including historical turns. */
export function AccountAnswer({ results }: { results: AccountResult[] }) {
  const balances = Array.from(new Map(results.flatMap((result) => result.kind === "ACCOUNT_BALANCE"
    ? [[result.account_id, result] as const] : [])).values());
  const accounts = Array.from(new Map(results.flatMap((result) => result.kind === "ACCOUNT_LIST"
    ? result.accounts.map((account) => [account.account_id, account] as const) : [])).values());
  const unqueried = accounts.filter((account) => !balances.some((balance) => balance.account_id === account.account_id));
  const queriedAt = results.reduce((latest, result) => Date.parse(result.as_of) > Date.parse(latest)
    ? result.as_of : latest, results[0]?.as_of ?? "");
  const hasDebt = balances.some((balance) => balance.account_type === "CREDIT" && balance.balance.startsWith("-"));

  return <div aria-label="账户查询回复" className="space-y-3 leading-7">
    <p>{balances.length ? "已查到你的账户余额：" : accounts.length ? "你目前有以下账户：" : "你目前没有可查询的账户。"}</p>
    <ul className="list-disc space-y-1 pl-5">
      {balances.map((balance) => <li key={balance.account_id}>
        {balance.display_name}（{balance.masked_number}）：<strong className="tabular-nums">{balance.balance_display}</strong>（{balance.currency}）。
      </li>)}
      {unqueried.map((account) => <li key={account.account_id}>
        {account.display_name}（{account.masked_number}，{account.currency}）{balances.length ? "：尚未查询余额。" : "。"}
      </li>)}
    </ul>
    {hasDebt && <p>信用卡负余额表示欠款，不计入可用存款。</p>}
    {queriedAt && <p className="text-xs text-slate-500">查询时间：<time dateTime={queriedAt}>{queryTime(queriedAt)}</time></p>}
  </div>;
}
