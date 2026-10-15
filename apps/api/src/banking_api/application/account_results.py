from pydantic import TypeAdapter

from banking_api.domain.account import AccountQueryResult, AccountQueryResults
from banking_api.runtime.base import SuccessfulToolResult

_RESULTS_ADAPTER = TypeAdapter(AccountQueryResults)
_ACCOUNT_CAPABILITIES = frozenset({"account.list", "account.get_balance"})


def build_account_results(results: list[SuccessfulToolResult]) -> list[AccountQueryResult]:
    """Persist only validated bank Tool output, never an LLM answer or arguments."""
    return _RESULTS_ADAPTER.validate_python(
        [result.output for result in results if result.capability_id in _ACCOUNT_CAPABILITIES]
    )


def account_query_answer(results: list[SuccessfulToolResult]) -> str:
    """Render bank facts when a deterministic anomaly/report answer replaces model prose."""
    facts = build_account_results(results)
    balances = [f for f in facts if f.kind == "ACCOUNT_BALANCE"]
    if balances:
        return "\n".join(f"{f.display_name}当前余额：{f.balance_display}" for f in balances)
    accounts = [a for f in facts if f.kind == "ACCOUNT_LIST" for a in f.accounts]
    return "本人账户：" + "、".join(a.display_name for a in accounts) if accounts else ""
