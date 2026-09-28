from datetime import UTC, datetime
from typing import Any

import httpx
import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.config.settings import Settings
from banking_api.domain.principal import Principal
from banking_api.persistence.repositories.identities import IdentityRepository
from banking_api.security.authentication.jwks import (
    JWKSCache,
    JWKSKeyNotFoundError,
    JWKSLoadError,
)


class AuthenticationError(Exception):
    code = "INVALID_CREDENTIAL"


class MissingCredentialError(AuthenticationError):
    code = "MISSING_CREDENTIAL"


class IdentityNotProvisionedError(Exception):
    code = "IDENTITY_NOT_PROVISIONED"


class AuthenticationService:
    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._jwks = (
            JWKSCache(
                issuer=settings.oidc_issuer,
                jwks_url=settings.oidc_jwks_url,
                cache_seconds=settings.oidc_jwks_cache_seconds,
                http_client=http_client,
            )
            if settings.auth_mode == "oidc"
            else None
        )

    async def authenticate(self, *, bearer_token: str | None, session: AsyncSession) -> Principal:
        if self._settings.auth_mode == "development":
            return Principal(
                user_id=self._settings.development_user_id,
                issuer="urn:ai-banking:development",
                subject=self._settings.development_user_id,
            )
        if not bearer_token:
            raise MissingCredentialError("Bearer credential is required")
        claims = await self._verify_oidc_token(bearer_token)
        issuer = str(claims["iss"])
        subject = str(claims["sub"])
        mapping = await IdentityRepository(session).get_by_external_identity(
            issuer=issuer,
            subject=subject,
        )
        if mapping is None:
            raise IdentityNotProvisionedError
        auth_time = self._parse_auth_time(claims.get("auth_time"))
        raw_amr = claims.get("amr")
        amr = tuple(str(item) for item in raw_amr) if isinstance(raw_amr, list) else ()
        acr = claims.get("acr")
        return Principal(
            user_id=mapping.user_id,
            issuer=issuer,
            subject=subject,
            auth_time=auth_time,
            amr=amr,
            acr=str(acr) if isinstance(acr, str) else None,
        )

    async def _verify_oidc_token(self, token: str) -> dict[str, Any]:
        assert self._jwks is not None
        try:
            header = jwt.get_unverified_header(token)
            algorithm = header.get("alg")
            kid = header.get("kid")
            if algorithm not in self._settings.oidc_allowed_algorithms:
                raise AuthenticationError("JWT signing algorithm is not allowed")
            if not isinstance(kid, str) or not kid:
                raise AuthenticationError("JWT kid is required")
            key = await self._jwks.get_signing_key(kid)
            claims = jwt.decode(
                token,
                key=key,
                algorithms=self._settings.oidc_allowed_algorithms,
                audience=self._settings.oidc_audience,
                issuer=self._settings.oidc_issuer,
                leeway=self._settings.oidc_clock_skew_seconds,
                options={
                    "require": ["exp", "iss", "aud", "sub"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )
        except AuthenticationError:
            raise
        except (
            jwt.PyJWTError,
            JWKSLoadError,
            JWKSKeyNotFoundError,
            ValueError,
            TypeError,
        ) as exc:
            raise AuthenticationError("Bearer credential is invalid") from exc
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise AuthenticationError("JWT subject is invalid")
        return claims

    @staticmethod
    def _parse_auth_time(value: Any) -> datetime | None:
        if isinstance(value, int | float):
            try:
                return datetime.fromtimestamp(value, tz=UTC)
            except (OverflowError, OSError, ValueError):
                return None
        return None
