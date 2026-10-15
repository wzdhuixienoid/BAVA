"""The real-provider smoke entry point must accept historical report fixtures."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from test_monthly_spending_report_skill import valid_narrative

from banking_api.llm.fake_provider import FakeLLMProvider


async def test_monthly_report_smoke_preserves_golden_numbers_with_current_schema(
    monkeypatch, capsys
):
    path = Path(__file__).resolve().parents[3] / "scripts/smoke_monthly_report_skill.py"
    spec = importlib.util.spec_from_file_location("monthly_skill_smoke", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module,
        "Settings",
        lambda: SimpleNamespace(
            llm_base_url="http://test/v1",
            llm_api_key="test-key",
            llm_model="fake",
            llm_provider="openai_compatible",
            llm_timeout_seconds=1,
        ),
    )
    provider = FakeLLMProvider([valid_narrative()])
    monkeypatch.setattr(module, "OpenAICompatibleProvider", lambda **kwargs: provider)
    await module.main()
    assert len(provider.requests) == 1
    assert provider.requests[0].tools == []
    assert "'golden_core_equal': True" in capsys.readouterr().out
