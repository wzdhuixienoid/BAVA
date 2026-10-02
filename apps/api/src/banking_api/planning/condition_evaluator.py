"""Pure evaluation of bounded, already scoped read snapshots. No external dependencies."""

import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import ValidationError

from banking_api.financial.analysis_snapshot import FinancialAnalysisSnapshot
from banking_api.planning.models import (
    PREDICATE_SOURCES,
    ConditionDecision,
    ConditionPredicate,
    ConditionSpec,
)
from banking_api.subscriptions.models import SubscriptionAnalysisSnapshot
from banking_api.tools.models import BalanceResult


class ConditionEvaluationError(Exception):
    retryable = False

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def source_output_hash(output: dict) -> str:
    canonical = json.dumps(
        output, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    if len(canonical) > 65536:
        raise ConditionEvaluationError("CONDITION_INPUT_UNAVAILABLE")
    return hashlib.sha256(canonical).hexdigest()


class PlanConditionEvaluator:
    def evaluate(
        self,
        spec: ConditionSpec,
        *,
        source_step_id: UUID,
        source_capability: str | None,
        source_status: str,
        output: dict | None,
    ) -> ConditionDecision:
        if (
            source_status != "COMPLETED"
            or output is None
            or source_capability != PREDICATE_SOURCES[spec.predicate]
        ):
            raise ConditionEvaluationError("CONDITION_INPUT_UNAVAILABLE")
        try:
            digest = source_output_hash(output)
            values = self._values(spec, output)
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            raise ConditionEvaluationError("CONDITION_INPUT_UNAVAILABLE") from exc
        if not values or any(
            not amount.is_finite() or not re.fullmatch(r"[A-Z]{3}", currency)
            for amount, currency in values
        ):
            raise ConditionEvaluationError("CONDITION_INPUT_UNAVAILABLE")
        if spec.currency is None:
            if len({currency for _, currency in values}) != 1:
                raise ConditionEvaluationError("CONDITION_CURRENCY_REQUIRED")
            currency = values[0][1]
        else:
            currency = spec.currency
        selected = [amount for amount, unit in values if unit == currency]
        if not selected:
            raise ConditionEvaluationError("CONDITION_CURRENCY_MISMATCH")
        if len(selected) != 1:
            raise ConditionEvaluationError("CONDITION_INPUT_UNAVAILABLE")
        actual = selected[0]
        threshold = Decimal(spec.threshold)
        return ConditionDecision(
            predicate=spec.predicate,
            source_step_id=source_step_id,
            source_output_hash=digest,
            actual_value=str(actual),
            threshold_value=str(threshold),
            currency=currency,
            outcome="TRUE" if actual >= threshold else "FALSE",
            evaluated_at=datetime.now(UTC),
        )

    def _values(self, spec: ConditionSpec, output: dict) -> list[tuple[Decimal, str]]:
        if spec.predicate == ConditionPredicate.ACCOUNT_BALANCE_AT_LEAST:
            balances = [
                BalanceResult.model_validate(item)
                for item in output["account_results"]
                if "balance" in item
            ]
            # Account lists can aid selection; require exactly one selected balance.
            if len(balances) != 1 or not balances[0].account_id:
                raise ConditionEvaluationError("CONDITION_INPUT_UNAVAILABLE")
            return [(balances[0].balance, balances[0].currency)]
        if spec.predicate == ConditionPredicate.MONTHLY_SPENDING_AT_LEAST:
            snapshot = FinancialAnalysisSnapshot.model_validate(output["analysis_snapshot"])
            summary = snapshot.spending_summary
            if summary is None or not snapshot.period or summary.period != snapshot.period:
                raise ConditionEvaluationError("CONDITION_INPUT_UNAVAILABLE")
            return [(summary.total_spending, summary.currency)]
        snapshot = SubscriptionAnalysisSnapshot.model_validate(
            output["subscription_analysis_snapshot"]
        )
        return [(cost.amount, cost.currency) for cost in snapshot.monthly_cost_by_currency]
