from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from banking_api.domain.enums import (
    ExecutorType,
    MessageRole,
    ReportType,
    RequestedOutput,
    RuntimeBackend,
    TaskStatus,
)
from banking_api.persistence.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class ConversationModel(Base):
    __tablename__ = "conversations"

    conversation_id: Mapped[UUID] = mapped_column("id", Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    messages: Mapped[list["MessageModel"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    tasks: Mapped[list["TaskModel"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class MessageModel(Base):
    __tablename__ = "messages"

    message_id: Mapped[UUID] = mapped_column("id", Uuid, primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole, name="message_role"))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    conversation: Mapped[ConversationModel] = relationship(back_populates="messages")


class TaskModel(Base):
    __tablename__ = "tasks"

    task_id: Mapped[UUID] = mapped_column("id", Uuid, primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    task_type: Mapped[str] = mapped_column(String(255))
    runtime_backend: Mapped[RuntimeBackend] = mapped_column(
        Enum(RuntimeBackend, name="runtime_backend"), default=RuntimeBackend.MANUAL
    )
    executor_type: Mapped[ExecutorType | None] = mapped_column(
        Enum(ExecutorType, name="executor_type"), nullable=True
    )
    executor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requested_output: Mapped[RequestedOutput | None] = mapped_column(
        Enum(RequestedOutput, name="requested_output"), nullable=True
    )
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus, name="task_status"), index=True)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    progress_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    conversation: Mapped[ConversationModel] = relationship(back_populates="tasks")


class ReportModel(Base):
    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint(
            "source_task_id",
            "report_type",
            "report_version",
            name="uq_reports_source_task_type_version",
        ),
        Index("ix_reports_user_created_at", "user_id", "created_at"),
        Index("ix_reports_conversation_created_at", "conversation_id", "created_at"),
    )

    report_id: Mapped[UUID] = mapped_column("id", Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    source_task_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    report_type: Mapped[ReportType] = mapped_column(
        Enum(ReportType, name="report_type")
    )
    report_version: Mapped[int] = mapped_column(Integer)
    skill_id: Mapped[str] = mapped_column(String(255))
    skill_version: Mapped[int] = mapped_column(Integer)
    period: Mapped[str] = mapped_column(String(7), index=True)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_snapshot_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )


class EventModel(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_conversation_sequence", "conversation_id", "sequence"),)

    # The database-generated primary key is the durable global event sequence.
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[UUID] = mapped_column("id", Uuid, unique=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(255), index=True)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    data_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
