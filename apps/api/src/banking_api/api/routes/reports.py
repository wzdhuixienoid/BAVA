from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from banking_api.api.dependencies import PrincipalDependency, SessionDependency
from banking_api.application.report_service import ReportNotFoundError, ReportService
from banking_api.domain.report import ReportListItem, ReportResponse

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_model=list[ReportListItem])
async def list_reports(
    session: SessionDependency,
    principal: PrincipalDependency,
    conversation_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ReportListItem]:
    return await ReportService(session).list_reports_for_user(
        user_id=principal.user_id,
        conversation_id=conversation_id,
        limit=limit,
        offset=offset,
    )


@router.get("/{report_id}", response_model=ReportResponse)
async def get_report(
    report_id: UUID,
    session: SessionDependency,
    principal: PrincipalDependency,
) -> ReportResponse:
    try:
        return await ReportService(session).get_report_for_user(
            report_id,
            user_id=principal.user_id,
        )
    except ReportNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到该报告") from exc
