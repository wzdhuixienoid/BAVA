from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from statistics import median
from typing import Any

from banking_api.financial.anomaly_models import (
    TransactionAnomalyEvidence,
    TransactionAnomalyItem,
    TransactionAnomalySeverity,
    TransactionAnomalySnapshot,
    TransactionAnomalyType,
)
from banking_api.mock_bank.service import MockBankService
from banking_api.subscriptions.detector import SubscriptionDetector, normalize_merchant

BASELINE_LOOKBACK_DAYS = 90
MIN_BASELINE_SAMPLES = 8
DUPLICATE_WINDOW_MINUTES = 10
MAX_ANOMALIES = 50


@dataclass
class _Finding:
    transaction: dict[str, Any]
    anomaly_types: set[TransactionAnomalyType] = field(default_factory=set)
    severities: list[TransactionAnomalySeverity] = field(default_factory=list)
    reason_codes: set[str] = field(default_factory=set)
    evidence: dict[TransactionAnomalyType, TransactionAnomalyEvidence] = field(
        default_factory=dict
    )
    related_ids: set[str] = field(default_factory=set)


class TransactionAnomalyDetector:
    """Deterministic, Principal-scoped anomaly analysis over posted debit facts."""

    def __init__(self, bank: MockBankService) -> None:
        self.bank = bank
        self.subscription_detector = SubscriptionDetector()

    def detect(
        self,
        *,
        user_id: str,
        generated_at: datetime | None = None,
        analysis_days: int = 30,
    ) -> TransactionAnomalySnapshot:
        now = self._as_utc(generated_at or datetime.now(UTC))
        analysis_start = now - timedelta(days=analysis_days)
        rows = [
            item
            for item in self.bank.list_transactions(user_id=user_id)
            if item.get("status") == "POSTED"
            and item.get("direction") == "DEBIT"
            and self._occurred_at(item) <= now
        ]
        candidates = [item for item in rows if self._occurred_at(item) >= analysis_start]
        findings: dict[str, _Finding] = {}
        baseline_sufficient = False

        for item in sorted(candidates, key=self._occurred_at):
            if item.get("category") == "TRANSFER":
                continue
            occurred_at = self._occurred_at(item)
            currency = str(item["currency"]).upper()
            baseline = [
                previous
                for previous in rows
                if previous.get("category") != "TRANSFER"
                and str(previous["currency"]).upper() == currency
                and occurred_at - timedelta(days=BASELINE_LOOKBACK_DAYS)
                <= self._occurred_at(previous)
                < occurred_at
            ]
            if len(baseline) < MIN_BASELINE_SAMPLES:
                continue
            baseline_sufficient = True
            baseline_median = median([self._amount(previous) for previous in baseline])
            if baseline_median <= 0:
                continue
            amount = self._amount(item)
            ratio = self._ratio(amount, baseline_median)
            finding = findings.setdefault(str(item["transaction_id"]), _Finding(item))
            if ratio >= Decimal("4"):
                self._add(
                    finding,
                    TransactionAnomalyType.AMOUNT_SPIKE,
                    TransactionAnomalySeverity.HIGH
                    if ratio >= Decimal("8")
                    else TransactionAnomalySeverity.MEDIUM,
                    "AMOUNT_AT_LEAST_4X_BASELINE_MEDIAN",
                    TransactionAnomalyEvidence(
                        baseline_median=baseline_median,
                        amount=amount,
                        ratio=ratio,
                        sample_count=len(baseline),
                    ),
                )
            merchant_key = normalize_merchant(str(item["merchant"]))
            merchant_seen = any(
                normalize_merchant(str(previous["merchant"])) == merchant_key
                for previous in baseline
            )
            if not merchant_seen and ratio >= Decimal("3"):
                self._add(
                    finding,
                    TransactionAnomalyType.NEW_MERCHANT_HIGH_AMOUNT,
                    TransactionAnomalySeverity.HIGH
                    if ratio >= Decimal("6")
                    else TransactionAnomalySeverity.MEDIUM,
                    "NEW_MERCHANT_AND_AMOUNT_AT_LEAST_3X_BASELINE_MEDIAN",
                    TransactionAnomalyEvidence(
                        baseline_median=baseline_median,
                        amount=amount,
                        ratio=ratio,
                        sample_count=len(baseline),
                        merchant_seen_in_lookback=False,
                    ),
                )

        self._detect_rapid_duplicates(candidates, findings)
        self._detect_subscription_price_spikes(rows, analysis_start, findings)
        items = [self._to_item(finding) for finding in findings.values() if finding.anomaly_types]
        items.sort(key=lambda item: item.occurred_at, reverse=True)
        return TransactionAnomalySnapshot(
            user_scope="CURRENT_PRINCIPAL",
            analysis_period_started_at=analysis_start,
            analysis_period_ended_at=now,
            baseline_lookback_days=BASELINE_LOOKBACK_DAYS,
            insufficient_baseline=not baseline_sufficient,
            anomalies=items[:MAX_ANOMALIES],
            generated_at=now,
        )

    def _detect_rapid_duplicates(
        self, candidates: list[dict[str, Any]], findings: dict[str, _Finding]
    ) -> None:
        grouped: dict[tuple[str, str, Decimal], list[dict[str, Any]]] = defaultdict(list)
        for item in candidates:
            if item.get("category") == "TRANSFER":
                continue
            grouped[
                (
                    normalize_merchant(str(item["merchant"])),
                    str(item["currency"]).upper(),
                    self._amount(item),
                )
            ].append(item)
        window = timedelta(minutes=DUPLICATE_WINDOW_MINUTES)
        for group in grouped.values():
            ordered = sorted(group, key=self._occurred_at)
            segment_start = 0
            for index in range(1, len(ordered) + 1):
                segment_ended = index == len(ordered) or (
                    self._occurred_at(ordered[index])
                    - self._occurred_at(ordered[index - 1])
                    > window
                )
                if not segment_ended:
                    continue
                self._add_duplicate_burst(
                    ordered[segment_start:index], findings, window
                )
                segment_start = index

    def _add_duplicate_burst(
        self,
        ordered: list[dict[str, Any]],
        findings: dict[str, _Finding],
        window: timedelta,
    ) -> None:
        if len(ordered) < 2:
            return
        best: list[dict[str, Any]] = []
        start = 0
        for end, current in enumerate(ordered):
            while self._occurred_at(current) - self._occurred_at(ordered[start]) > window:
                start += 1
            cluster = ordered[start : end + 1]
            if len(cluster) >= len(best):
                best = cluster
        if len(best) < 2:
            return
        current = best[-1]
        finding = findings.setdefault(str(current["transaction_id"]), _Finding(current))
        count = len(best)
        self._add(
            finding,
            TransactionAnomalyType.RAPID_DUPLICATE,
            TransactionAnomalySeverity.HIGH
            if count >= 3
            else TransactionAnomalySeverity.MEDIUM,
            "EXACT_DUPLICATE_WITHIN_10_MINUTES",
            TransactionAnomalyEvidence(
                amount=self._amount(current),
                duplicate_count=count,
                window_minutes=DUPLICATE_WINDOW_MINUTES,
            ),
        )
        finding.related_ids.update(str(item["transaction_id"]) for item in best)

    def _detect_subscription_price_spikes(
        self,
        rows: list[dict[str, Any]],
        analysis_start: datetime,
        findings: dict[str, _Finding],
    ) -> None:
        for subscription in self.subscription_detector.detect(rows):
            current = subscription.last
            if self._occurred_at(current) < analysis_start:
                continue
            previous_amount = self._amount(subscription.previous)
            current_amount = self._amount(current)
            if previous_amount <= 0 or current_amount <= previous_amount:
                continue
            increase_percent = self._ratio(
                current_amount - previous_amount, previous_amount
            ) * Decimal("100")
            if increase_percent < Decimal("30"):
                continue
            finding = findings.setdefault(str(current["transaction_id"]), _Finding(current))
            self._add(
                finding,
                TransactionAnomalyType.SUBSCRIPTION_PRICE_SPIKE,
                TransactionAnomalySeverity.HIGH
                if increase_percent >= Decimal("50")
                else TransactionAnomalySeverity.MEDIUM,
                "SUBSCRIPTION_PRICE_INCREASE_AT_LEAST_30_PERCENT",
                TransactionAnomalyEvidence(
                    previous_amount=previous_amount,
                    current_amount=current_amount,
                    increase_percent=increase_percent,
                ),
            )
            finding.related_ids.update(
                [
                    str(subscription.previous["transaction_id"]),
                    str(current["transaction_id"]),
                ]
            )

    @staticmethod
    def _add(
        finding: _Finding,
        anomaly_type: TransactionAnomalyType,
        severity: TransactionAnomalySeverity,
        reason_code: str,
        evidence: TransactionAnomalyEvidence,
    ) -> None:
        finding.anomaly_types.add(anomaly_type)
        finding.severities.append(severity)
        finding.reason_codes.add(reason_code)
        finding.evidence[anomaly_type] = evidence

    @classmethod
    def _to_item(cls, finding: _Finding) -> TransactionAnomalyItem:
        transaction = finding.transaction
        severity = (
            TransactionAnomalySeverity.HIGH
            if TransactionAnomalySeverity.HIGH in finding.severities
            else TransactionAnomalySeverity.MEDIUM
        )
        return TransactionAnomalyItem(
            transaction_id=str(transaction["transaction_id"]),
            occurred_at=cls._occurred_at(transaction),
            merchant_display=str(transaction["merchant"]),
            amount=cls._amount(transaction),
            currency=str(transaction["currency"]).upper(),
            anomaly_types=sorted(finding.anomaly_types, key=lambda item: item.value),
            severity=severity,
            reason_codes=sorted(finding.reason_codes),
            evidence=finding.evidence,
            related_transaction_ids=sorted(finding.related_ids)[:10],
        )

    @staticmethod
    def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
        with localcontext() as context:
            context.prec = 28
            return numerator / denominator

    @staticmethod
    def _amount(item: dict[str, Any]) -> Decimal:
        return Decimal(str(item["amount"]))

    @staticmethod
    def _occurred_at(item: dict[str, Any]) -> datetime:
        return TransactionAnomalyDetector._as_utc(
            datetime.fromisoformat(str(item["occurred_at"]).replace("Z", "+00:00"))
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
