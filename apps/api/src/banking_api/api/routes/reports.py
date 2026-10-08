from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response

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
    deleted: bool = False,
) -> list[ReportListItem]:
    return await ReportService(session).list_reports_for_user(
        user_id=principal.user_id,
        conversation_id=conversation_id,
        limit=limit,
        offset=offset,
        deleted=deleted,
    )


@router.get("/{report_id}", response_model=ReportResponse)
async def get_report(
    request: Request,
    report_id: UUID,
    session: SessionDependency,
    principal: PrincipalDependency,
) -> ReportResponse:
    try:
        report = await ReportService(session).get_report_for_user(
            report_id,
            user_id=principal.user_id,
        )
        referenced = {item.account_id for item in report.content.top_transactions}
        referenced.update(report.content.scope.account_ids)
        names = {
            item["account_id"]: item["display_name"]
            for item in request.app.state.mock_bank.list_accounts(user_id=principal.user_id)
            if item["account_id"] in referenced
        }
        return report.model_copy(update={"account_names": names})
    except ReportNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到该报告") from exc


@router.delete("/{report_id}", status_code=204)
async def delete_report(
    report_id: UUID, session: SessionDependency, principal: PrincipalDependency
) -> Response:
    try:
        await ReportService(session).set_deleted(report_id, user_id=principal.user_id, deleted=True)
        await session.commit()
        return Response(status_code=204)
    except ReportNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到该报告") from exc


@router.post("/{report_id}/restore", status_code=204)
async def restore_report(
    report_id: UUID, session: SessionDependency, principal: PrincipalDependency
) -> Response:
    try:
        await ReportService(session).set_deleted(
            report_id, user_id=principal.user_id, deleted=False
        )
        await session.commit()
        return Response(status_code=204)
    except ReportNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到该报告") from exc
