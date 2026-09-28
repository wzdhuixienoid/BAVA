import json
from pathlib import Path

from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.mock_bank.service import MockBankService

USER_ID = "dev-user-001"

DATA_DIR = Path(__file__).parents[1] / "src/banking_api/mock_bank/data"


def load_golden() -> dict[str, object]:
    return json.loads((DATA_DIR / "golden_financial_metrics.json").read_text(encoding="utf-8"))


def test_july_and_august_summaries_match_committed_golden_exactly() -> None:
    service = FinancialAnalyticsService(MockBankService())
    golden = load_golden()["months"]

    assert (
        service.spending_summary("2026-07", user_id=USER_ID).model_dump(mode="json")
        == golden["2026-07"]["summary"]
    )
    assert (
        service.spending_summary("2026-08", user_id=USER_ID).model_dump(mode="json")
        == golden["2026-08"]["summary"]
    )
    assert golden["2026-07"]["summary"]["total_spending"] == "9333.20"
    assert golden["2026-08"]["summary"]["total_spending"] == "16547.30"


def test_august_category_breakdown_matches_committed_golden_exactly() -> None:
    service = FinancialAnalyticsService(MockBankService())
    expected = load_golden()["months"]["2026-08"]["category_breakdown"]

    actual = service.category_breakdown("2026-08", user_id=USER_ID)
    assert actual.model_dump(mode="json") == expected
    categories = {item["category"]: item for item in expected["categories"]}
    assert categories["FOOD"]["amount"] == "1005.30"
    assert categories["TRAVEL"]["amount"] == "4260.00"
    assert "TRANSFER" not in categories


def test_august_top_transactions_match_committed_golden_exactly() -> None:
    service = FinancialAnalyticsService(MockBankService())
    expected = load_golden()["months"]["2026-08"]["top_transactions"]

    actual = service.top_transactions("2026-08", limit=5, user_id=USER_ID)
    assert actual.model_dump(mode="json") == expected
    assert [item["transaction_id"] for item in expected["transactions"]] == [
        "txn_0014",
        "txn_0113",
        "txn_0116",
        "txn_0119",
        "txn_0115",
    ]


def test_july_to_august_comparison_matches_committed_golden_exactly() -> None:
    service = FinancialAnalyticsService(MockBankService())
    expected = load_golden()["comparisons"]["2026-07_to_2026-08"]

    assert service.compare_periods("2026-08", user_id=USER_ID).model_dump(mode="json") == expected
    assert expected["absolute_change"] == "7214.10"
    changes = {item["category"]: item for item in expected["category_changes"]}
    assert changes["FOOD"]["absolute_change"] == "589.10"
    assert changes["TRAVEL"] == {
        "category": "TRAVEL",
        "current_amount": "4260.00",
        "previous_amount": "0",
        "absolute_change": "4260.00",
        "percentage_change": None,
    }


def test_golden_rules_pin_posted_status_and_transfer_exclusion() -> None:
    golden = load_golden()
    rules = golden["calculation_rules"]

    assert golden["fixture_version"] == "0.3.2"
    assert rules["valid_transaction_statuses"] == ["POSTED"]
    assert rules["excluded_spending_categories"] == ["TRANSFER"]
    assert rules["excluded_income_categories"] == ["TRANSFER"]
    assert rules["money_type"] == "Decimal"
