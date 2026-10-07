from fastapi import APIRouter, HTTPException, Query, Request

from banking_api.api.dependencies import PrincipalDependency, SessionDependency
from banking_api.payees.service import PayeeCreate, PayeeService
from banking_api.security.guard import (
    SecurityGuardService,
    SecurityGuardStatus,
    acquire_security_user_lock,
)
from banking_api.tools.models import PayeeSummary

router = APIRouter(prefix="/payees", tags=["payees"])


@router.get("", response_model=list[PayeeSummary])
async def list_payees(
    request: Request,
    session: SessionDependency,
    principal: PrincipalDependency,
    query: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return await PayeeService(request.app.state.mock_bank, session).list(
        user_id=principal.user_id, query=query, limit=limit, offset=offset
    )


@router.post("", response_model=PayeeSummary)
async def create_payee(
    body: PayeeCreate, request: Request, session: SessionDependency, principal: PrincipalDependency
):
    await acquire_security_user_lock(session, principal.user_id)
    guard = await SecurityGuardService(session).get_status(user_id=principal.user_id)
    if guard.status is SecurityGuardStatus.WRITE_LOCKED:
        raise HTTPException(status_code=423, detail="SECURITY_WRITE_LOCKED")
    try:
        item = await PayeeService(request.app.state.mock_bank, session).create(
            body, user_id=principal.user_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return item
