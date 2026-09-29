from datetime import UTC, datetime, timedelta
from decimal import Decimal

from banking_api.financial.anomaly_detector import TransactionAnomalyDetector
from banking_api.financial.anomaly_models import (
    TransactionAnomalySeverity,
    TransactionAnomalyType,
)


class FixtureBank:
    def __init__(self, by_user):  # type: ignore[no-untyped-def]
        self.by_user = by_user

    def list_transactions(self, *, user_id: str):  # type: ignore[no-untyped-def]
        return [dict(item) for item in self.by_user.get(user_id, [])]


def transaction(
    transaction_id: str,
    occurred_at: datetime,
    merchant: str,
    amount: str,
    *,
    currency: str = "CNY",
    category: str = "SHOPPING",
) -> dict[str, str]:
    return {
        "transaction_id": transaction_id,
        "account_id": "account",
        "occurred_at": occurred_at.isoformat(),
        "merchant": merchant,
        "description": "synthetic test fact",
        "amount": amount,
        "currency": currency,
        "direction": "DEBIT",
        "category": category,
        "status": "POSTED",
    }


def baseline(now: datetime, *, currency: str = "CNY") -> list[dict[str, str]]:
    return [
        transaction(
            f"base-{index}",
            now - timedelta(days=20 - index),
            "历史商户",
            "100.00",
            currency=currency,
        )
        for index in range(8)
    ]


def test_amount_spike_new_merchant_merge_and_severity() -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    rows = baseline(now) + [transaction("current", now - timedelta(days=1), "XYZ", "900.00")]
    snapshot = TransactionAnomalyDetector(FixtureBank({"a": rows})).detect(
        user_id="a", generated_at=now
    )

    assert len(snapshot.anomalies) == 1
    item = snapshot.anomalies[0]
    assert set(item.anomaly_types) == {
        TransactionAnomalyType.AMOUNT_SPIKE,
        TransactionAnomalyType.NEW_MERCHANT_HIGH_AMOUNT,
    }
    assert item.severity is TransactionAnomalySeverity.HIGH
    assert item.evidence[TransactionAnomalyType.AMOUNT_SPIKE].baseline_median == Decimal(
        "100.00"
    )
    assert item.evidence[TransactionAnomalyType.AMOUNT_SPIKE].ratio == Decimal("9")


def test_cold_start_does_not_invent_long_term_anomaly() -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    rows = baseline(now)[:4] + [
        transaction("current", now - timedelta(days=1), "XYZ", "10000.00")
    ]
    snapshot = TransactionAnomalyDetector(FixtureBank({"a": rows})).detect(
        user_id="a", generated_at=now
    )

    assert snapshot.insufficient_baseline is True
    assert snapshot.anomalies == []


def test_rapid_exact_duplicate_is_high_but_nearby_amounts_are_not() -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    rows = [
        transaction("d1", now - timedelta(minutes=9), "星河便利店", "299.00"),
        transaction("d2", now - timedelta(minutes=5), "星河便利店", "299.00"),
        transaction("d3", now - timedelta(minutes=1), "星河便利店", "299.00"),
        transaction("near1", now - timedelta(minutes=4), "其他商户", "298.00"),
        transaction("near2", now - timedelta(minutes=3), "其他商户", "300.00"),
    ]
    snapshot = TransactionAnomalyDetector(FixtureBank({"a": rows})).detect(
        user_id="a", generated_at=now
    )

    assert len(snapshot.anomalies) == 1
    item = snapshot.anomalies[0]
    assert item.transaction_id == "d3"
    assert item.anomaly_types == [TransactionAnomalyType.RAPID_DUPLICATE]
    assert item.severity is TransactionAnomalySeverity.HIGH
    assert item.evidence[TransactionAnomalyType.RAPID_DUPLICATE].duplicate_count == 3


def test_subscription_price_spike_reuses_deterministic_sequence() -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    rows = [
        transaction("s1", now - timedelta(days=32), "星幕视频", "30.00", category="SUBSCRIPTION"),
        transaction(
            "s2",
            now - timedelta(days=1),
            "星幕视频会员",
            "42.00",
            category="SUBSCRIPTION",
        ),
    ]
    snapshot = TransactionAnomalyDetector(FixtureBank({"a": rows})).detect(
        user_id="a", generated_at=now
    )

    item = snapshot.anomalies[0]
    assert item.anomaly_types == [TransactionAnomalyType.SUBSCRIPTION_PRICE_SPIKE]
    assert item.severity is TransactionAnomalySeverity.MEDIUM
    evidence = item.evidence[TransactionAnomalyType.SUBSCRIPTION_PRICE_SPIKE]
    assert evidence.previous_amount == Decimal("30.00")
    assert evidence.current_amount == Decimal("42.00")
    assert evidence.increase_percent == Decimal("40.0")


def test_currency_and_principal_baselines_are_isolated() -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    rows_a = baseline(now, currency="CNY") + [
        transaction("usd", now - timedelta(days=1), "USD NEW", "900.00", currency="USD")
    ]
    rows_b = baseline(now, currency="USD") + [
        transaction("usd-b", now - timedelta(days=1), "USD NEW", "900.00", currency="USD")
    ]
    detector = TransactionAnomalyDetector(FixtureBank({"a": rows_a, "b": rows_b}))

    assert detector.detect(user_id="a", generated_at=now).anomalies == []
    b_snapshot = detector.detect(user_id="b", generated_at=now)
    assert b_snapshot.anomalies[0].transaction_id == "usd-b"
