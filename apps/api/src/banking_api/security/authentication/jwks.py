import asyncio
import time
from collections.abc import Mapping
from typing import Any

import httpx
import jwt


class JWKSLoadError(Exception):
    pass


class JWKSKeyNotFoundError(Exception):
    pass


class JWKSCache:
    """Loads keys only from configured OIDC metadata and refreshes once for an unknown kid."""

    def __init__(
        self,
        *,
        issuer: str,
        jwks_url: str,
        cache_seconds: int,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._issuer = issuer
        self._configured_jwks_url = jwks_url
        self._cache_seconds = cache_seconds
        self._http_client = http_client
        self._keys: dict[str, Mapping[str, Any]] = {}
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def get_signing_key(self, kid: str) -> Any:
        if not kid:
            raise JWKSKeyNotFoundError("JWT kid is required")
        if time.monotonic() >= self._expires_at:
            await self._refresh()
        jwk = self._keys.get(kid)
        if jwk is None:
            await self._refresh(force=True)
            jwk = self._keys.get(kid)
        if jwk is None:
            raise JWKSKeyNotFoundError("JWT signing key was not found")
        try:
            return jwt.PyJWK.from_dict(dict(jwk)).key
        except (jwt.PyJWKError, ValueError, TypeError) as exc:
            raise JWKSLoadError("OIDC signing key is invalid") from exc

    async def _refresh(self, *, force: bool = False) -> None:
        async with self._lock:
            if not force and time.monotonic() < self._expires_at:
                return
            owns_client = self._http_client is None
            client = self._http_client or httpx.AsyncClient(
                timeout=5.0,
                follow_redirects=False,
            )
            try:
                jwks_url = self._configured_jwks_url or await self._discover_jwks_url(client)
                response = await client.get(jwks_url)
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                raise JWKSLoadError("Unable to load OIDC JWKS") from exc
            finally:
                if owns_client:
                    await client.aclose()
            raw_keys = payload.get("keys") if isinstance(payload, dict) else None
            if not isinstance(raw_keys, list):
                raise JWKSLoadError("OIDC JWKS does not contain a keys array")
            keys = {
                str(item["kid"]): item
                for item in raw_keys
                if isinstance(item, dict) and isinstance(item.get("kid"), str)
            }
            if not keys:
                raise JWKSLoadError("OIDC JWKS contains no keyed signing keys")
            self._keys = keys
            self._expires_at = time.monotonic() + self._cache_seconds

    async def _discover_jwks_url(self, client: httpx.AsyncClient) -> str:
        discovery_url = f"{self._issuer.rstrip('/')}/.well-known/openid-configuration"
        response = await client.get(discovery_url)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("issuer") != self._issuer:
            raise JWKSLoadError("OIDC discovery issuer does not match configuration")
        jwks_uri = payload.get("jwks_uri")
        if not isinstance(jwks_uri, str) or not jwks_uri:
            raise JWKSLoadError("OIDC discovery does not provide jwks_uri")
        return jwks_uri
