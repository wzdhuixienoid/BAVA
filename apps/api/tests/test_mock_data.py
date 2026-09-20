import runpy
from pathlib import Path


def test_committed_mock_data_is_valid() -> None:
    validator = runpy.run_path(
        str(Path(__file__).parents[3] / "scripts" / "validate_mock_data.py")
    )["validate"]

    assert validator() == {
        "accounts": 4,
        "transactions": 138,
        "payees": 6,
        "subscriptions": 5,
    }
