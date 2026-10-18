"""RFC 6238 authenticator possession factor, encrypted at rest and replay fenced."""

import base64
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlencode
from uuid import UUID

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.twofactor.totp import TOTP
from sqlalchemy import select, update

from banking_api.audit.domain import record_action
from banking_api.domain.enums import ReauthenticationStatus
from banking_api.domain.reauthentication import ReauthenticationMethod
from banking_api.persistence.models import ReauthenticationModel, TotpCredentialModel
from banking_api.security.guard import acquire_security_user_lock
from banking_api.security.reauthentication.provider import ReauthenticationChallenge


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class MfaError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def totp_code(secret: str, counter: int, *, digits: int = 6) -> str:
    key = base64.b32decode(secret, casefold=True)
    return TOTP(key, digits, hashes.SHA1(), 30).generate(counter * 30).decode()


class TotpCredentialService:
    def __init__(self, session, settings, *, clock=lambda: datetime.now(UTC)):
        self.session = session
        self.settings = settings
        self.clock = clock
        self.cipher = Fernet(settings.mfa_encryption_key.encode())

    async def credential(self, user_id):
        return await self.session.scalar(
            select(TotpCredentialModel)
            .where(
                TotpCredentialModel.user_id == user_id,
            )
            .with_for_update()
        )

    def decrypt(self, ciphertext):
        return self.cipher.decrypt(ciphertext.encode()).decode()

    def counter(self, ciphertext, code):
        if not re.fullmatch(r"[0-9]{6}", code):
            return None
        secret = self.decrypt(ciphertext)
        current = int(utc(self.clock()).timestamp()) // 30
        for counter in (current, current - 1, current + 1):
            if hmac.compare_digest(totp_code(secret, counter), code):
                return counter
        return None

    async def _check_lock(self, credential):
        if credential.locked_until and utc(credential.locked_until) > utc(self.clock()):
            raise MfaError("MFA_LOCKED", "认证器验证已暂时锁定，请稍后重试")
        if credential.locked_until:
            credential.locked_until = None
            credential.failure_count = 0

    async def _failure(self, user_id, credential):
        credential.failure_count += 1
        if credential.failure_count >= 3:
            credential.locked_until = utc(self.clock()) + timedelta(minutes=15)
        await record_action(
            self.session,
            user_id=user_id,
            action="mfa.enrollment.verify",
            resource_id=user_id,
            payload={},
            outcome="DENIED",
            evidence=[{"stage": "verification", "verified": False}],
        )
        raise MfaError("MFA_INVALID_CODE", "动态码无效、已使用或已过期")

    async def begin(self, user_id, *, current_code=""):
        await acquire_security_user_lock(self.session, user_id)
        row = await self.credential(user_id)
        if row is None:
            row = TotpCredentialModel(user_id=user_id, last_counter=-1, failure_count=0)
            self.session.add(row)
            await self.session.flush()
        await self._check_lock(row)
        if row.secret_ciphertext:
            matched = self.counter(row.secret_ciphertext, current_code)
            if matched is None or matched <= row.last_counter:
                await self._failure(user_id, row)
            row.last_counter = matched
        secret = base64.b32encode(secrets.token_bytes(20)).decode()
        row.pending_ciphertext = self.cipher.encrypt(secret.encode()).decode()
        row.pending_expires_at = utc(self.clock()) + timedelta(minutes=5)
        await record_action(
            self.session,
            user_id=user_id,
            action="mfa.enrollment.begin",
            resource_id=user_id,
            payload={},
            outcome="PENDING",
            evidence=[{"stage": "primary_identity_verified"}],
        )
        return {
            "secret": secret,
            "otpauth_uri": "otpauth://totp/"
            + quote(self.settings.mfa_issuer + ":" + user_id, safe="")
            + "?"
            + urlencode(
                {
                    "secret": secret,
                    "issuer": self.settings.mfa_issuer,
                    "algorithm": "SHA1",
                    "digits": 6,
                    "period": 30,
                }
            ),
            "expires_at": row.pending_expires_at,
        }

    async def confirm(self, user_id, code):
        await acquire_security_user_lock(self.session, user_id)
        row = await self.credential(user_id)
        if (
            row is None
            or not row.pending_ciphertext
            or not row.pending_expires_at
            or utc(row.pending_expires_at) <= utc(self.clock())
        ):
            raise MfaError("MFA_ENROLLMENT_EXPIRED", "请重新绑定认证器")
        await self._check_lock(row)
        matched = self.counter(row.pending_ciphertext, code)
        if matched is None:
            await self._failure(user_id, row)
        row.secret_ciphertext = row.pending_ciphertext
        row.pending_ciphertext = None
        row.pending_expires_at = None
        row.confirmed_at = utc(self.clock())
        row.last_counter = matched
        row.failure_count = 0
        await record_action(
            self.session,
            user_id=user_id,
            action="mfa.enrollment.confirm",
            resource_id=user_id,
            payload={},
            outcome="SUCCEEDED",
            evidence=[{"stage": "possession_verified"}],
        )

    async def consume(self, user_id, code):
        """Consume a possession proof in the caller's business transaction."""
        await acquire_security_user_lock(self.session, user_id)
        row = await self.credential(user_id)
        if row is None or not row.secret_ciphertext:
            raise MfaError("MFA_ENROLLMENT_REQUIRED", "请先完成认证器绑定")
        await self._check_lock(row)
        counter = self.counter(row.secret_ciphertext, code)
        if counter is None:
            return False
        changed = await self.session.execute(
            update(TotpCredentialModel)
            .where(
                TotpCredentialModel.user_id == user_id,
                TotpCredentialModel.last_counter < counter,
            )
            .values(last_counter=counter)
        )
        return changed.rowcount == 1


class TotpReauthenticationProvider:
    def __init__(self, session, settings, *, clock=lambda: datetime.now(UTC)):
        self.session = session
        self.service = TotpCredentialService(session, settings, clock=clock)
        self.clock = clock

    async def start_challenge(self, *, user_id: str, workflow_id: UUID, approval_id: UUID):
        row = await self.service.credential(user_id)
        if row is None or not row.secret_ciphertext:
            raise MfaError("MFA_ENROLLMENT_REQUIRED", "请先完成认证器绑定")
        return ReauthenticationChallenge(
            method=ReauthenticationMethod.TOTP,
            provider_reference=secrets.token_urlsafe(32),
        )

    async def verify(
        self,
        *,
        user_id,
        workflow_id,
        approval_id,
        provider_reference,
        verification_code,
    ):
        if not provider_reference:
            return False
        await acquire_security_user_lock(self.session, user_id)
        challenge = await self.session.scalar(
            select(ReauthenticationModel)
            .where(
                ReauthenticationModel.user_id == user_id,
                ReauthenticationModel.workflow_id == workflow_id,
                ReauthenticationModel.approval_id == approval_id,
                ReauthenticationModel.provider_reference == provider_reference,
                ReauthenticationModel.method == ReauthenticationMethod.TOTP,
                ReauthenticationModel.status == ReauthenticationStatus.PENDING,
            )
            .with_for_update()
        )
        if challenge is None or utc(challenge.expires_at) <= utc(self.clock()):
            return False
        return await self.service.consume(user_id, verification_code)
