import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location(
    "report_stability", SCRIPTS / "smoke_report_stability.py"
)
stability = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stability)


async def test_stability_counts_every_run_and_rejects_numeric_mismatch(monkeypatch, capsys):
    attempts = []

    async def product():
        attempts.append(1)
        if len(attempts) == 3:
            raise RuntimeError("Persisted report core does not match Golden fixture")
        if len(attempts) == 7:
            raise RuntimeError("REPORT_NARRATIVE_VALIDATION_FAILED")
        if len(attempts) == 9:
            raise ConnectionError("transport failure must not interrupt counters")

    monkeypatch.setattr(
        stability,
        "Settings",
        lambda: SimpleNamespace(app_environment="test", database_url="sqlite:///report_test.db"),
    )
    monkeypatch.setattr(stability, "report_product", product)
    monkeypatch.setattr(sys, "argv", ["stability", "--runs", "10"])
    with pytest.raises(SystemExit) as error:
        await stability.main()
    assert error.value.code == 1
    assert len(attempts) == 10
    output = capsys.readouterr().out
    assert '"successes": 7' in output and '"golden_mismatches": 1' in output
    assert '"validation_failures": 1' in output
    assert '"other_failures": 1' in output
    assert "transport failure must not interrupt counters" not in output


async def test_stability_refuses_production_before_model_call(monkeypatch):
    monkeypatch.setattr(
        stability,
        "Settings",
        lambda: SimpleNamespace(
            app_environment="production", database_url="sqlite:///report_test.db"
        ),
    )
    monkeypatch.setattr(sys, "argv", ["stability", "--runs", "10"])
    with pytest.raises(SystemExit, match="isolated test database"):
        await stability.main()
