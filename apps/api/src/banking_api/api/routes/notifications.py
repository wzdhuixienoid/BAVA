from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import func, select

from banking_api.api.dependencies import PrincipalDependency, SessionDependency
from banking_api.financial.anomaly_models import TransactionAnomalySnapshot
from banking_api.persistence.models import NotificationModel

router = APIRouter(prefix="/notifications", tags=["notifications"])


class Notification(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    notification_id: UUID
    kind: str
    title: str
    message: str
    schedule_id: UUID | None
    created_at: datetime
    read_at: datetime | None
    anomaly_snapshot: TransactionAnomalySnapshot | None = None

    @field_validator("created_at", "read_at")
    @classmethod
    def utc_timestamp(cls, value):
        return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


class NotificationInbox(BaseModel):
    items: list[Notification]
    unread_count: int
    has_more: bool


@router.get("", response_model=NotificationInbox)
async def list_notifications(
    session: SessionDependency,
    principal: PrincipalDependency,
    offset: int = Query(default=0, ge=0),
):
    visible = (
        NotificationModel.user_id == principal.user_id,
        NotificationModel.deleted_at.is_(None),
    )
    rows = (
        await session.scalars(
            select(NotificationModel)
            .where(*visible)
            .order_by(NotificationModel.created_at.desc(), NotificationModel.notification_id.desc())
            .offset(offset)
            .limit(101)
        )
    ).all()
    unread = await session.scalar(
        select(func.count())
        .select_from(NotificationModel)
        .where(*visible, NotificationModel.read_at.is_(None))
    )
    return NotificationInbox(
        items=[Notification.model_validate(row) for row in rows[:100]],
        unread_count=unread or 0,
        has_more=len(rows) > 100,
    )


async def owned(session, notification_id, user_id, *, lock=True):
    statement = select(NotificationModel).where(
        NotificationModel.notification_id == notification_id,
        NotificationModel.user_id == user_id,
        NotificationModel.deleted_at.is_(None),
    )
    if lock:
        statement = statement.with_for_update()
    row = await session.scalar(statement)
    if row is None:
        raise HTTPException(404, detail="未找到该消息")
    return row


@router.get("/{notification_id}", response_model=Notification)
async def get_notification(
    notification_id: UUID,
    session: SessionDependency,
    principal: PrincipalDependency,
):
    return Notification.model_validate(
        await owned(session, notification_id, principal.user_id, lock=False)
    )


@router.post("/{notification_id}/read", response_model=Notification)
async def read_notification(
    notification_id: UUID,
    session: SessionDependency,
    principal: PrincipalDependency,
):
    row = await owned(session, notification_id, principal.user_id)
    row.read_at = row.read_at or datetime.now(UTC)
    await session.commit()
    return Notification.model_validate(row)


@router.delete("/{notification_id}", status_code=204)
async def delete_notification(
    notification_id: UUID,
    session: SessionDependency,
    principal: PrincipalDependency,
):
    row = await owned(session, notification_id, principal.user_id)
    row.deleted_at = datetime.now(UTC)
    await session.commit()
    return Response(status_code=204)
