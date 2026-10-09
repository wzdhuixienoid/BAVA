
from fastapi import APIRouter, HTTPException, Query, Request

from banking_api.api.dependencies import PrincipalDependency, SessionDependency
from banking_api.payees.service import PayeeCreate, PayeeService, PayeeUpdate
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


async def require_payee_write(session, user_id: str) -> None:
    await acquire_security_user_lock(session, user_id)
    guard = await SecurityGuardService(session).get_status(user_id=user_id)
    if guard.status is SecurityGuardStatus.WRITE_LOCKED:
        raise HTTPException(status_code=423, detail="SECURITY_WRITE_LOCKED")


@router.patch("/{payee_id}", response_model=PayeeSummary)
async def update_payee(
    payee_id: str,
    body: PayeeUpdate,
    request: Request,
    session: SessionDependency,
    principal: PrincipalDependency,
):
    await require_payee_write(session, principal.user_id)
    try:
        item = await PayeeService(request.app.state.mock_bank, session).update(
            payee_id, body, user_id=principal.user_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return item


@router.delete("/{payee_id}", status_code=204)
async def delete_payee(
    payee_id: str,
    request: Request,
    session: SessionDependency,
    principal: PrincipalDependency,
):
    await require_payee_write(session, principal.user_id)
    try:
        await PayeeService(request.app.state.mock_bank, session).delete(
            payee_id, user_id=principal.user_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
