from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from banking_api.api.dependencies import PrincipalDependency, SessionDependency
from banking_api.audit.domain import DomainActionAudit, record_action
from banking_api.config.settings import get_settings
from banking_api.persistence.models import DomainActionAuditModel, TotpCredentialModel
from banking_api.security.guard import SecurityGuardService, SecurityStatus
from banking_api.security.read_consent import approve_subscription_read
from banking_api.security.reauthentication.totp_provider import MfaError, TotpCredentialService
from banking_api.security.transfer_preferences import (
    TransferSecurityPreference,
    TransferSecurityPreferenceConflict,
    transfer_security_preference,
    update_transfer_security_preference,
)

router = APIRouter(prefix="/security", tags=["security"])


class TransferLimitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: Decimal = Field(ge=0, le=200, max_digits=5, decimal_places=2)
    expected_version: int = Field(ge=0)
    confirmed: Literal[True]
    verification_code: str = Field(min_length=1, max_length=256, repr=False)


@router.get("/transfer-preference", response_model=TransferSecurityPreference)
async def get_transfer_preference(session: SessionDependency, principal: PrincipalDependency):
    return await transfer_security_preference(session, principal.user_id)


@router.post("/transfer-preference", response_model=TransferSecurityPreference)
async def save_transfer_preference(
    body: TransferLimitInput,
    session: SessionDependency,
    principal: PrincipalDependency,
):
    from sqlalchemy.exc import IntegrityError

    from banking_api.security.guard import SecurityWriteLockedError

    try:
        result = await update_transfer_security_preference(
            session,
            principal.user_id,
            amount=body.amount,
            expected_version=body.expected_version,
            verification_code=body.verification_code,
        )
    except MfaError as exc:
        await record_transfer_preference_denial(session, principal.user_id, body, exc.code)
        await session.commit()  # Persist failed verification counters and denial audit.
        raise
    except (TransferSecurityPreferenceConflict, IntegrityError) as exc:
        await session.rollback()
        await record_transfer_preference_denial(
            session, principal.user_id, body, "VERSION_CONFLICT"
        )
        await session.commit()
        raise HTTPException(status_code=409, detail="额度设置已更新，请刷新后重新核对") from exc
    except SecurityWriteLockedError as exc:
        await session.rollback()
        await record_transfer_preference_denial(session, principal.user_id, body, "WRITE_LOCKED")
        await session.commit()
        raise HTTPException(status_code=423, detail="安全保护已启动，请稍后重试") from exc
    await session.commit()
    return result


async def record_transfer_preference_denial(session, user_id, body, reason):
    await record_action(
        session,
        user_id=user_id,
        action="transfer.passwordless_limit.update",
        resource_id=user_id,
        payload={"amount": str(body.amount), "expected_version": body.expected_version},
        outcome="DENIED",
        evidence=[{"stage": "security.preference.check", "error_code": reason}],
    )


@router.get("/status", response_model=SecurityStatus)
async def get_security_status(
    session: SessionDependency, principal: PrincipalDependency
) -> SecurityStatus:
    status = await SecurityGuardService(session).get_status(principal.user_id)
    await session.commit()
    return status


class ReadConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]


@router.post("/subscription-read-consent")
async def subscription_read_consent(
    body: ReadConfirmation,
    session: SessionDependency,
    principal: PrincipalDependency,
):
    expiry = await approve_subscription_read(session, principal.user_id)
    await session.commit()
    return {"capability": "subscription.analyze", "expires_at": expiry}


@router.get("/audit", response_model=list[DomainActionAudit])
async def action_audit(
    session: SessionDependency,
    principal: PrincipalDependency,
    offset: int = Query(default=0, ge=0, le=10000),
):
    return list(
        await session.scalars(
            select(DomainActionAuditModel)
            .where(
                DomainActionAuditModel.user_id == principal.user_id,
            )
            .order_by(
                DomainActionAuditModel.created_at.desc(), DomainActionAuditModel.trace_id.desc()
            )
            .offset(offset)
            .limit(50)
        )
    )


@router.get("/audit/{trace_id}", response_model=DomainActionAudit)
async def action_audit_detail(
    trace_id: UUID,
    session: SessionDependency,
    principal: PrincipalDependency,
):
    row = await session.get(DomainActionAuditModel, trace_id)
    if row is None or row.user_id != principal.user_id:
        raise HTTPException(status_code=404, detail="未找到该审计记录")
    return row


class MfaStatus(BaseModel):
    method: Literal["mock", "totp"]
    enrolled: bool


class MfaEnrollmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_code: str = Field(default="", max_length=6, repr=False)


class MfaEnrollment(BaseModel):
    secret: str = Field(repr=False)
    otpauth_uri: str = Field(repr=False)
    expires_at: datetime


class MfaConfirmationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^[0-9]{6}$", repr=False)


def require_mfa_setup(principal):
    settings = get_settings()
    if settings.reauth_provider != "totp":
        raise HTTPException(status_code=409, detail="当前为模拟验证模式")
    if settings.auth_mode == "oidc":
        now = datetime.now(UTC)
        if (
            principal.auth_time is None
            or not 0 <= (now - principal.auth_time).total_seconds() <= 300
        ):
            raise HTTPException(status_code=403, detail="绑定认证器前，请重新登录验证身份")
    return settings


@router.get("/mfa", response_model=MfaStatus, response_model_exclude_none=True)
async def mfa_status(
    session: SessionDependency, principal: PrincipalDependency, response: Response
):
    settings = get_settings()
    response.headers["Cache-Control"] = "no-store"
    row = await session.get(TotpCredentialModel, principal.user_id)
    return MfaStatus(
        method=settings.reauth_provider,
        enrolled=bool(row and row.secret_ciphertext),
    )


@router.post("/mfa/enrollment", response_model=MfaEnrollment)
async def mfa_enrollment(
    body: MfaEnrollmentInput,
    session: SessionDependency,
    principal: PrincipalDependency,
    response: Response,
):
    settings = require_mfa_setup(principal)
    response.headers["Cache-Control"] = "no-store"
    await SecurityGuardService(session).require_write_allowed(principal.user_id)
    try:
        result = await TotpCredentialService(session, settings).begin(
            principal.user_id,
            current_code=body.current_code,
        )
    except MfaError:
        await session.commit()  # Retain failed enrollment attempts and lock evidence.
        raise
    await session.commit()
    return result


@router.post("/mfa/enrollment/confirm", response_model=MfaStatus, response_model_exclude_none=True)
async def mfa_enrollment_confirm(
    body: MfaConfirmationInput,
    session: SessionDependency,
    principal: PrincipalDependency,
):
    settings = require_mfa_setup(principal)
    await SecurityGuardService(session).require_write_allowed(principal.user_id)
    try:
        await TotpCredentialService(session, settings).confirm(principal.user_id, body.code)
    except MfaError:
        await session.commit()
        raise
    await session.commit()
    return MfaStatus(method="totp", enrolled=True)
