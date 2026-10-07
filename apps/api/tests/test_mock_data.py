import runpy
from pathlib import Path


def test_committed_mock_data_is_valid() -> None:
    validator = runpy.run_path(
        str(Path(__file__).parents[3] / "scripts" / "validate_mock_data.py")
    )["validate"]

    assert validator() == {
        "accounts": 4,
        "transactions": 1207,
        "payees": 6,
        "subscriptions": 5,
    }


def test_synthetic_history_is_reproducible_and_matches_committed_fixture() -> None:
    import json

    root = Path(__file__).parents[3]
    build = runpy.run_path(str(root / "scripts/generate_mock_data.py"))["build_transactions"]
    committed = json.loads(
        (root / "apps/api/src/banking_api/mock_bank/data/transactions.json").read_text()
    )
    assert build() == committed
    assert build() == build()


def test_synthetic_history_exercises_all_supported_anomaly_rules() -> None:
    from datetime import UTC, datetime

    from banking_api.financial.anomaly_detector import TransactionAnomalyDetector
    from banking_api.mock_bank.service import MockBankService

    detector = TransactionAnomalyDetector(MockBankService())
    types = set()
    for when in [datetime(2026, 3, 21, tzinfo=UTC), datetime(2026, 10, 7, 23, 59, tzinfo=UTC)]:
        snapshot = detector.detect(user_id="dev-user-001", generated_at=when)
        types.update(kind.value for item in snapshot.anomalies for kind in item.anomaly_types)
    assert types == {
        "AMOUNT_SPIKE",
        "NEW_MERCHANT_HIGH_AMOUNT",
        "RAPID_DUPLICATE",
        "SUBSCRIPTION_PRICE_SPIKE",
    }
