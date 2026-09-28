import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError
from sqlalchemy import select

from banking_api.config.settings import Settings
from banking_api.persistence.models import EventModel, TaskModel
from banking_api.persistence.repositories.identities import IdentityRepository
from banking_api.security.authentication import AuthenticationService

ISSUER = "https://issuer.test"
AUDIENCE = "banking-api"
KID = "test-key-1"


def signing_material():  # type: ignore[no-untyped-def]
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": KID, "use": "sig", "alg": "RS256"})
    return private_key, jwk


def oidc_settings(**overrides) -> Settings:  # type: ignore[no-untyped-def]
    values = {
        "auth_mode": "oidc",
        "app_environment": "test",
        "oidc_issuer": ISSUER,
        "oidc_audience": AUDIENCE,
        "oidc_jwks_url": f"{ISSUER}/jwks",
        "oidc_allowed_algorithms": ["RS256"],
        "oidc_clock_skew_seconds": 0,
    }
    values.update(overrides)
    return Settings(**values)


def token(
    private_key,  # type: ignore[no-untyped-def]
    *,
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    subject: str = "subject-a",
    expires_delta: timedelta = timedelta(minutes=5),
    not_before_delta: timedelta = timedelta(seconds=-1),
    algorithm: str = "RS256",
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": issuer,
            "aud": audience,
            "sub": subject,
            "iat": now,
            "nbf": now + not_before_delta,
            "exp": now + expires_delta,
            "auth_time": int(now.timestamp()),
            "amr": ["pwd"],
        },
        private_key,
        algorithm=algorithm,
        headers={"kid": KID},
    )


def service_with_jwks(settings: Settings, jwk: dict) -> AuthenticationService:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(settings.oidc_jwks_url)
        return httpx.Response(200, json={"keys": [jwk]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = AuthenticationService(settings, http_client=client)
    service._test_http_client = client  # type: ignore[attr-defined]
    return service


async def test_valid_oidc_token_maps_to_internal_principal(app, client) -> None:
    private_key, jwk = signing_material()
    service = service_with_jwks(oidc_settings(), jwk)
    app.state.authentication_service = service
    async with app.state.test_session_factory() as session:
        await IdentityRepository(session).provision(
            user_id="user-a", issuer=ISSUER, subject="subject-a"
        )
        await session.commit()

    encoded = token(private_key)
    headers = {"Authorization": f"Bearer {encoded}"}
    response = await client.post(
        "/api/v1/conversations", headers=headers, json={"title": "OIDC task"}
    )

    assert response.status_code == 201
    accepted = await client.post(
        f"/api/v1/conversations/{response.json()['conversation_id']}/messages",
        headers=headers,
        json={"content": "hello"},
    )
    assert accepted.status_code == 202
    task_id = accepted.json()["task_id"]
    await app.state.task_runner.run(UUID(task_id))
    async with app.state.test_session_factory() as session:
        task = await session.get(TaskModel, UUID(task_id))
        events = list(
            (
                await session.execute(select(EventModel).where(EventModel.task_id == UUID(task_id)))
            ).scalars()
        )
    assert task is not None and task.user_id == "user-a"
    persisted = str(
        {
            "input": task.input_json,
            "output": task.output_json,
            "error": task.error_json,
            "events": [event.data_json for event in events],
        }
    )
    assert encoded not in persisted
    assert "Authorization" not in persisted
    await service._test_http_client.aclose()  # type: ignore[attr-defined]


async def test_missing_token_is_401_in_oidc_mode(app, client) -> None:
    _, jwk = signing_material()
    service = service_with_jwks(oidc_settings(), jwk)
    app.state.authentication_service = service

    response = await client.get("/api/v1/conversations")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "MISSING_CREDENTIAL"
    await service._test_http_client.aclose()  # type: ignore[attr-defined]


async def test_unprovisioned_identity_is_403(app, client) -> None:
    private_key, jwk = signing_material()
    service = service_with_jwks(oidc_settings(), jwk)
    app.state.authentication_service = service

    response = await client.get(
        "/api/v1/conversations",
        headers={"Authorization": f"Bearer {token(private_key, subject='unknown')}"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "IDENTITY_NOT_PROVISIONED"
    await service._test_http_client.aclose()  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "case",
    [
        "bad_signature",
        "expired",
        "not_yet_valid",
        "wrong_issuer",
        "wrong_audience",
        "unsupported_alg",
    ],
)
async def test_invalid_oidc_tokens_are_rejected(app, client, case: str) -> None:
    private_key, jwk = signing_material()
    other_key, _ = signing_material()
    service = service_with_jwks(oidc_settings(), jwk)
    kwargs = {}
    signing_key = private_key
    if case == "bad_signature":
        signing_key = other_key
    elif case == "expired":
        kwargs["expires_delta"] = timedelta(seconds=-1)
    elif case == "not_yet_valid":
        kwargs["not_before_delta"] = timedelta(minutes=5)
    elif case == "wrong_issuer":
        kwargs["issuer"] = "https://wrong-issuer.test"
    elif case == "wrong_audience":
        kwargs["audience"] = "wrong-audience"
    elif case == "unsupported_alg":
        unsigned = jwt.encode(
            {
                "iss": ISSUER,
                "aud": AUDIENCE,
                "sub": "subject-a",
                "exp": datetime.now(UTC) + timedelta(minutes=5),
            },
            key="test-secret-that-is-at-least-32-bytes-long",
            algorithm="HS256",
            headers={"kid": KID},
        )
        encoded = unsigned
    if case != "unsupported_alg":
        encoded = token(signing_key, **kwargs)
    app.state.authentication_service = service
    response = await client.get(
        "/api/v1/conversations",
        headers={"Authorization": f"Bearer {encoded}"},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "INVALID_CREDENTIAL"
    await service._test_http_client.aclose()  # type: ignore[attr-defined]


async def test_identity_namespace_includes_issuer(app) -> None:
    async with app.state.test_session_factory() as session:
        repository = IdentityRepository(session)
        first = await repository.provision(
            user_id="user-a", issuer="https://issuer-a.test", subject="same-subject"
        )
        second = await repository.provision(
            user_id="user-b", issuer="https://issuer-b.test", subject="same-subject"
        )
        await session.commit()
        assert first.user_id != second.user_id


def test_production_rejects_development_auth() -> None:
    with pytest.raises(ValidationError, match="forbidden in production"):
        Settings(auth_mode="development", app_environment="production")


async def test_unknown_kid_refreshes_cached_jwks(app) -> None:
    old_private, old_jwk = signing_material()
    new_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    new_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(new_private.public_key()))
    new_jwk.update({"kid": "rotated-key", "use": "sig", "alg": "RS256"})
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        keys = [old_jwk] if calls == 1 else [old_jwk, new_jwk]
        return httpx.Response(200, json={"keys": keys})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = AuthenticationService(oidc_settings(), http_client=http_client)
    async with app.state.test_session_factory() as session:
        await IdentityRepository(session).provision(
            user_id="user-a", issuer=ISSUER, subject="subject-a"
        )
        await session.commit()
        assert (
            await service.authenticate(bearer_token=token(old_private), session=session)
        ).user_id == "user-a"
        now = datetime.now(UTC)
        rotated = jwt.encode(
            {
                "iss": ISSUER,
                "aud": AUDIENCE,
                "sub": "subject-a",
                "nbf": now - timedelta(seconds=1),
                "exp": now + timedelta(minutes=5),
            },
            new_private,
            algorithm="RS256",
            headers={"kid": "rotated-key"},
        )
        assert (
            await service.authenticate(bearer_token=rotated, session=session)
        ).user_id == "user-a"
    assert calls == 2
    await http_client.aclose()
