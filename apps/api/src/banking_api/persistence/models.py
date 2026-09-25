from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from banking_api.domain.approval import ApprovalType
from banking_api.domain.enums import (
    ApprovalStatus,
    ExecutorType,
    MessageRole,
    OperationStatus,
    ReauthenticationStatus,
    ReportType,
    RequestedOutput,
    RuntimeBackend,
    TaskStatus,
    WorkflowStatus,
)
from banking_api.domain.operation import OperationType
from banking_api.domain.reauthentication import ReauthenticationMethod
from banking_api.domain.workflow import WorkflowType
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


class WorkflowModel(Base):
    __tablename__ = "workflows"
    __table_args__ = (
        Index("ix_workflows_user_created_at", "user_id", "created_at"),
        Index("ix_workflows_conversation_created_at", "conversation_id", "created_at"),
    )

    workflow_id: Mapped[UUID] = mapped_column("id", Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    source_task_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), unique=True, index=True
    )
    workflow_type: Mapped[WorkflowType] = mapped_column(
        Enum(WorkflowType, name="workflow_type")
    )
    status: Mapped[WorkflowStatus] = mapped_column(
        Enum(WorkflowStatus, name="workflow_status"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ApprovalModel(Base):
    __tablename__ = "approvals"
    __table_args__ = (Index("ix_approvals_workflow_created_at", "workflow_id", "created_at"),)

    approval_id: Mapped[UUID] = mapped_column("id", Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    workflow_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    approval_type: Mapped[ApprovalType] = mapped_column(Enum(ApprovalType, name="approval_type"))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, name="approval_status"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_by_operation_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("operations.id", use_alter=True, name="fk_approvals_consumed_operation"),
        nullable=True,
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ReauthenticationModel(Base):
    __tablename__ = "reauthentications"
    __table_args__ = (Index("ix_reauth_workflow_created_at", "workflow_id", "created_at"),)

    reauth_id: Mapped[UUID] = mapped_column("id", Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    workflow_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    approval_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("approvals.id", ondelete="CASCADE"), index=True
    )
    method: Mapped[ReauthenticationMethod] = mapped_column(
        Enum(ReauthenticationMethod, name="reauthentication_method")
    )
    status: Mapped[ReauthenticationStatus] = mapped_column(
        Enum(ReauthenticationStatus, name="reauthentication_status"), index=True
    )
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class OperationModel(Base):
    __tablename__ = "operations"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id", "operation_type", name="uq_operations_workflow_type"
        ),
        Index("ix_operations_user_created_at", "user_id", "created_at"),
    )

    operation_id: Mapped[UUID] = mapped_column("id", Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    workflow_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    approval_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("approvals.id", ondelete="RESTRICT"), unique=True, index=True
    )
    operation_type: Mapped[OperationType] = mapped_column(
        Enum(OperationType, name="operation_type")
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[UUID] = mapped_column(Uuid, unique=True, index=True)
    status: Mapped[OperationStatus] = mapped_column(
        Enum(OperationStatus, name="operation_status"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class MockBankTransferModel(Base):
    __tablename__ = "mock_bank_transfers"

    provider_reference: Mapped[str] = mapped_column(String(255), primary_key=True)
    idempotency_key: Mapped[UUID] = mapped_column(Uuid, unique=True, index=True)
    source_account_id: Mapped[str] = mapped_column(String(255), index=True)
    payee_id: Mapped[str] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), index=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


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
