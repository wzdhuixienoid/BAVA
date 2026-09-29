from fastapi import APIRouter

from banking_api.api.dependencies import PrincipalDependency, SessionDependency
from banking_api.security.guard import SecurityGuardService, SecurityStatus

router = APIRouter(prefix="/security", tags=["security"])


@router.get("/status", response_model=SecurityStatus)
async def get_security_status(
    session: SessionDependency, principal: PrincipalDependency
) -> SecurityStatus:
    status = await SecurityGuardService(session).get_status(principal.user_id)
    await session.commit()
    return status
