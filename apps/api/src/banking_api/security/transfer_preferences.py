import hmac
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, computed_field
from sqlalchemy import select, update

from banking_api.audit.domain import record_action
from banking_api.config.settings import get_settings
from banking_api.financial.report_formatter import ReportFormatter
from banking_api.persistence.models import TransferSecurityPreferenceModel
from banking_api.security.guard import SecurityGuardService, acquire_security_user_lock
from banking_api.security.reauthentication.totp_provider import MfaError, TotpCredentialService


class TransferSecurityPreference(BaseModel):
    passwordless_limit: Decimal = Decimal("200.00")
    maximum: Decimal = Decimal("200.00")
    daily_threshold: Decimal = Decimal("1000.00")
    version: int = 0

    @computed_field
    @property
    def passwordless_limit_display(self) -> str:
        return ReportFormatter().money(self.passwordless_limit, "CNY")


async def transfer_security_preference(session, user_id):
    row = await session.get(TransferSecurityPreferenceModel, user_id)
    return (
        TransferSecurityPreference(
            passwordless_limit=row.passwordless_limit,
            version=row.version,
        )
        if row
        else TransferSecurityPreference()
    )


class TransferSecurityPreferenceConflict(Exception):
    pass


async def update_transfer_security_preference(
    session,
    user_id,
    *,
    amount,
    expected_version,
    verification_code,
):
    await acquire_security_user_lock(session, user_id)
    guard = SecurityGuardService(session)
    await guard.require_write_allowed(user_id)
    row = await session.scalar(
        select(TransferSecurityPreferenceModel)
        .where(
            TransferSecurityPreferenceModel.user_id == user_id,
        )
        .with_for_update()
    )
    if (row.version if row else 0) != expected_version:
        raise TransferSecurityPreferenceConflict
    settings = get_settings()
    if settings.reauth_provider == "totp":
        verified = await TotpCredentialService(session, settings).consume(
            user_id, verification_code
        )
    else:
        if settings.app_environment == "production":
            raise MfaError("MFA_UNAVAILABLE", "当前验证方式不可用")
        verified = hmac.compare_digest(
            verification_code.encode(), settings.mock_reauth_code.encode()
        )
    await guard.record_reauthentication_result(
        user_id=user_id,
        workflow_id=None,
        conversation_id=None,
        task_id=None,
        succeeded=verified,
    )
    if not verified:
        raise MfaError("MFA_INVALID_CODE", "验证码无效、已使用或已过期")
    before = row.passwordless_limit if row else Decimal("200.00")
    if row:
        updated = await session.execute(
            update(TransferSecurityPreferenceModel)
            .where(
                TransferSecurityPreferenceModel.user_id == user_id,
                TransferSecurityPreferenceModel.version == expected_version,
            )
            .values(
                passwordless_limit=amount,
                version=expected_version + 1,
                updated_at=datetime.now(UTC),
            )
        )
        if updated.rowcount != 1:
            raise TransferSecurityPreferenceConflict
    else:
        session.add(TransferSecurityPreferenceModel(user_id=user_id, passwordless_limit=amount))
        await session.flush()
    await record_action(
        session,
        user_id=user_id,
        action="transfer.passwordless_limit.update",
        resource_id=user_id,
        payload={"amount": str(amount), "expected_version": expected_version},
        outcome="SUCCEEDED",
        evidence=[
            {
                "stage": "user_confirmation",
                "confirmed": True,
                "previous_limit": str(before),
                "new_limit": str(amount),
            },
            {"stage": "possession_verified", "method": settings.reauth_provider},
            {"stage": "security.preference.saved", "version": expected_version + 1},
        ],
    )
    return TransferSecurityPreference(passwordless_limit=amount, version=expected_version + 1)
