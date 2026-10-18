import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text
from test_transfer_operations import operation_runtime

from banking_api import __version__
from banking_api.api.routes.demo import DemoReadiness
from banking_api.config.settings import get_settings
from banking_api.subscriptions.provider import MockSubscriptionProvider

spec = importlib.util.spec_from_file_location(
    "demo_preflight", Path(__file__).parents[3] / "scripts/demo_preflight.py"
)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def good():
    return dict(
        version=__version__,
        database_revision="0018",
        owner_is_demo_user=True,
        expected_accounts_exist=True,
        salary_balance_initial=True,
        daily_exposure_zero=True,
        subscriptions_match_fixture=True,
        security_guard_normal=True,
        unresolved_operations=0,
        provider_mode="Mock",
        reauthentication_mode="Mock",
        llm_configured=True,
        business_timezone="Asia/Shanghai",
        reference_time=None,
    )


def test_preflight_is_default_deny_per_check_and_never_exports_secret():
    data = good()
    assert all(preflight.evaluate(data, {"info": {"version": __version__}}, "0018").values())
    for key in data:
        if key == "reference_time":
            continue
        bad = {**data, key: None}
        assert not all(preflight.evaluate(bad, {"info": {"version": __version__}}, "0018").values())
    assert (
        not {"llm_api_key", "mock_reauth_code", "jwt", "authorization"}
        & DemoReadiness.model_fields.keys()
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://bank.example",
        "http://user:password@localhost",
        "http://192.168.0.1",
        "file:///tmp/test",
    ],
)
def test_preflight_rejects_nonlocal_or_credential_urls(url):
    with pytest.raises(ValueError):
        preflight.local_url(url)


async def test_readiness_is_read_only_and_production_rejects(app, client, monkeypatch):
    bank, provider, _, _ = operation_runtime(app)
    app.state.mock_bank = bank
    app.state.transfer_provider = provider
    app.state.subscription_provider = MockSubscriptionProvider(app.state.test_session_factory, bank)
    async with app.state.test_session_factory() as session:
        await session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        await session.execute(text("INSERT INTO alembic_version VALUES ('0018')"))
        await session.commit()
    response = await client.get("/api/v1/demo/readiness")
    assert response.status_code == 200
    data = response.json()
    for key in (
        "expected_accounts_exist",
        "salary_balance_initial",
        "daily_exposure_zero",
        "security_guard_normal",
        "subscriptions_match_fixture",
    ):
        assert data[key] is True, (key, data)
    assert data["unresolved_operations"] == 0
    assert data["reauthentication_mode"] == "Mock"
    monkeypatch.setattr(get_settings(), "reauth_provider", "totp")
    assert (await client.get("/api/v1/demo/readiness")).json()["reauthentication_mode"] == "TOTP"
    totp_data = {**good(), "reauthentication_mode": "TOTP"}
    assert all(preflight.evaluate(totp_data, {"info": {"version": __version__}}, "0018").values())
    assert (await client.post("/api/v1/demo/readiness")).status_code == 405
    monkeypatch.setattr(get_settings(), "app_environment", "production")
    assert (await client.get("/api/v1/demo/readiness")).status_code == 404
