from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from banking_api.api.dependencies import (
    EventBusDependency,
    PrincipalDependency,
    SessionDependency,
    TransferWorkflowEngineDependency,
)
from banking_api.application.aa_service import (
    MOCK_PARTICIPANTS,
    AAAction,
    AAPaymentAction,
    AAService,
    AAUpdate,
)
from banking_api.application.operation_service import OperationActionError
from banking_api.config.settings import get_settings
from banking_api.domain.workflow import Workflow
from banking_api.security.guard import SecurityWriteLockedError

router = APIRouter(tags=["AA Mock collections"])


def service(request, session, bus, engine):
    return AAService(session, bus, engine, request.app.state.mock_bank)


def fail(exc):
    raise HTTPException(
        423 if isinstance(exc, SecurityWriteLockedError) else 409, detail=str(exc)
    ) from exc


@router.get("/aa-requests")
async def list_aa(
    request: Request,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
    engine: TransferWorkflowEngineDependency,
):
    return await service(request, session, bus, engine).list(principal.user_id)


@router.get("/aa-requests/{request_id}")
async def get_aa(
    request_id: UUID,
    request: Request,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
    engine: TransferWorkflowEngineDependency,
):
    try:
        return await service(request, session, bus, engine).get(request_id, principal.user_id)
    except OperationActionError as exc:
        raise HTTPException(404, detail=str(exc)) from exc


@router.patch("/aa-requests/{request_id}")
async def update_aa(
    request_id: UUID,
    body: AAUpdate,
    request: Request,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
    engine: TransferWorkflowEngineDependency,
):
    try:
        return await service(request, session, bus, engine).update(
            request_id, principal.user_id, body
        )
    except (OperationActionError, SecurityWriteLockedError) as exc:
        fail(exc)


@router.post("/aa-requests/{request_id}/actions/publish")
async def publish_aa(
    request_id: UUID,
    body: AAAction,
    request: Request,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
    engine: TransferWorkflowEngineDependency,
):
    try:
        return await service(request, session, bus, engine).publish(
            request_id, principal.user_id, body.expected_version
        )
    except (OperationActionError, SecurityWriteLockedError) as exc:
        fail(exc)


@router.post("/aa-shares/{share_id}/actions/pay", response_model=Workflow)
async def pay_aa(
    share_id: UUID,
    body: AAPaymentAction,
    request: Request,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
    engine: TransferWorkflowEngineDependency,
):
    try:
        return await service(request, session, bus, engine).payment(
            share_id, principal.user_id, body.expected_version, body.source_account_id
        )
    except (OperationActionError, SecurityWriteLockedError) as exc:
        fail(exc)


@router.post("/aa-shares/{share_id}/actions/{action}")
async def close_aa(
    share_id: UUID,
    action: str,
    body: AAAction,
    request: Request,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
    engine: TransferWorkflowEngineDependency,
):
    if action not in {"reject", "cancel"}:
        raise HTTPException(404)
    try:
        return await service(request, session, bus, engine).close_share(
            share_id, principal.user_id, body.expected_version, reject=action == "reject"
        )
    except (OperationActionError, SecurityWriteLockedError) as exc:
        fail(exc)


class MockLogin(BaseModel):
    identity: str


@router.get("/mock-sessions")
async def mock_sessions(principal: PrincipalDependency):
    settings = get_settings()
    return {
        "enabled": settings.mock_participant_login_enabled,
        "current_user_id": principal.user_id,
        "identities": [
            {"name": "发起者", "identity": settings.development_user_id},
            *[{"name": name, "identity": user} for name, user in MOCK_PARTICIPANTS.items()],
        ]
        if settings.mock_participant_login_enabled
        else [],
    }


@router.post("/mock-sessions")
async def mock_login(body: MockLogin):
    settings = get_settings()
    if (
        not settings.mock_participant_login_enabled
        or settings.auth_mode != "development"
        or settings.app_environment == "production"
    ):
        raise HTTPException(404)
    if body.identity not in {*MOCK_PARTICIPANTS.values(), settings.development_user_id}:
        raise HTTPException(422, detail="未知的 Mock 身份")
    token = jwt.encode(
        {
            "sub": body.identity,
            "iss": "urn:banking:mock-session",
            "aud": "banking-mock",
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        settings.mock_participant_signing_key,
        algorithm="HS256",
    )
    return {"access_token": token, "mock": True, "expires_in": 3600}


@router.get("/aa-accounts")
async def aa_accounts(request: Request, principal: PrincipalDependency):
    rows = []
    for account in request.app.state.mock_bank.list_accounts(user_id=principal.user_id):
        if (
            account["status"] == "ACTIVE"
            and account["currency"] == "CNY"
            and account["account_type"] in {"DEBIT", "SAVINGS"}
        ):
            rows.append(
                {
                    **account,
                    "available_balance": format(
                        await request.app.state.transfer_provider.effective_balance(
                            principal.user_id, account["account_id"]
                        ),
                        ".2f",
                    ),
                }
            )
    return rows
