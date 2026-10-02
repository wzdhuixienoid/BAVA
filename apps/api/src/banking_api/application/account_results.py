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
