import pytest

from banking_api.api.dependencies import get_current_principal
from banking_api.config.settings import get_settings
from banking_api.domain.principal import Principal


async def test_private_environment_code_is_not_returned_and_can_verify_limit(
    app, client, monkeypatch
):
    monkeypatch.setattr(get_settings(), "mock_reauth_code", "135790")
    response = await client.get("/api/v1/security/mfa")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"method": "mock", "enrolled": False}
    assert "135790" not in response.text
    assert "demo_code" not in response.text
    openapi = (await client.get("/openapi.json")).text
    assert "135790" not in openapi and '"demo_code"' not in openapi
    saved = await client.post(
        "/api/v1/security/transfer-preference",
        json={
            "amount": "50",
            "expected_version": 0,
            "confirmed": True,
            "verification_code": "135790",
        },
    )
    assert saved.status_code == 200, saved.text
    assert (await client.get("/api/v1/security/transfer-preference")).json()[
        "passwordless_limit"
    ] == "50.00"


@pytest.mark.parametrize("environment,auth", [("development", "oidc"), ("production", "oidc")])
async def test_demo_code_is_never_exposed_outside_development_identity(
    app, client, monkeypatch, environment, auth
):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_environment", environment)
    monkeypatch.setattr(settings, "auth_mode", auth)
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="dev-user-001", issuer="test", subject="dev-user-001"
    )
    response = await client.get("/api/v1/security/mfa")
    assert response.status_code == 200
    assert "demo_code" not in response.json()
    assert settings.mock_reauth_code not in response.text


async def test_authenticator_mode_does_not_publish_demo_code(app, client, monkeypatch):
    monkeypatch.setattr(get_settings(), "reauth_provider", "totp")
    response = await client.get("/api/v1/security/mfa")
    assert response.json() == {"method": "totp", "enrolled": False}
