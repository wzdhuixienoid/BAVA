from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
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
    text,
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
    title_is_custom: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    messages: Mapped[list["MessageModel"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    tasks: Mapped[list["TaskModel"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class IdentityMappingModel(Base):
    __tablename__ = "identity_mappings"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_identity_mappings_issuer_subject"),
        Index("ix_identity_mappings_user_id", "user_id"),
    )

    identity_id: Mapped[UUID] = mapped_column("id", Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    issuer: Mapped[str] = mapped_column(String(2048), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


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
    workflow_type: Mapped[WorkflowType] = mapped_column(Enum(WorkflowType, name="workflow_type"))
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


class SecurityGuardStateModel(Base):
    __tablename__ = "security_guard_states"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lock_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reauth_failure_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    reauth_window_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    bypass_attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    bypass_window_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class OperationModel(Base):
    __tablename__ = "operations"
    __table_args__ = (
        UniqueConstraint("workflow_id", "operation_type", name="uq_operations_workflow_type"),
        Index("ix_operations_user_created_at", "user_id", "created_at"),
        Index(
            "ix_operations_recovery_due",
            "status",
            "next_reconcile_at",
            "lease_expires_at",
            postgresql_where=text("status IN ('CREATED', 'SUBMITTED', 'UNKNOWN')"),
        ),
        CheckConstraint(
            "reconcile_attempts >= 0", name="ck_operations_reconcile_attempts_nonnegative"
        ),
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
    risk_business_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
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
    next_reconcile_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reconcile_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_reconcile_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class MockBankTransferModel(Base):
    remark: Mapped[str] = mapped_column(String(100), default="", server_default="")
    destination_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    destination_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    aa_share_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True, unique=True)
    credited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __tablename__ = "mock_bank_transfers"

    provider_reference: Mapped[str] = mapped_column(String(255), primary_key=True)
    idempotency_key: Mapped[UUID] = mapped_column(Uuid, unique=True, index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    source_account_id: Mapped[str] = mapped_column(String(255), index=True)
    payee_id: Mapped[str] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), index=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MockSubscriptionCancellationModel(Base):
    __tablename__ = "mock_subscription_cancellations"

    provider_reference: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    subscription_id: Mapped[str] = mapped_column(String(255), index=True)
    idempotency_key: Mapped[UUID] = mapped_column(Uuid, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    __table_args__ = (
        Index(
            "ix_tasks_execution_due",
            "status",
            "next_run_at",
            "lease_expires_at",
            postgresql_where=text("status IN ('PENDING', 'RUNNING', 'INTERRUPTED')"),
        ),
        CheckConstraint(
            "execution_attempts >= 0",
            name="ck_tasks_execution_attempts_nonnegative",
        ),
    )

    task_id: Mapped[UUID] = mapped_column("id", Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
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
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=utc_now
    )
    execution_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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
    report_type: Mapped[ReportType] = mapped_column(Enum(ReportType, name="report_type"))
    report_version: Mapped[int] = mapped_column(Integer)
    skill_id: Mapped[str] = mapped_column(String(255))
    skill_version: Mapped[int] = mapped_column(Integer)
    period: Mapped[str] = mapped_column(String(7), index=True)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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


class OutboxEventModel(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_outbox_events_event_id"),
        CheckConstraint(
            "publish_attempts >= 0", name="ck_outbox_events_publish_attempts_nonnegative"
        ),
        Index(
            "ix_outbox_events_due",
            "next_publish_at",
            "lease_expires_at",
            "created_at",
            postgresql_where=text("published_at IS NULL"),
        ),
    )

    outbox_id: Mapped[UUID] = mapped_column("id", Uuid, primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    publish_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    next_publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)


class PlanModel(Base):
    __tablename__ = "plans"
    __table_args__ = (
        Index("ix_plans_user_created_at", "user_id", "created_at"),
        Index("ix_plans_conversation_created_at", "conversation_id", "created_at"),
    )

    plan_id: Mapped[UUID] = mapped_column("id", Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(255))
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE")
    )
    source_task_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), unique=True
    )
    goal_summary: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30))
    version: Mapped[int] = mapped_column(Integer, default=1)
    manual_takeover: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlanStepModel(Base):
    __tablename__ = "plan_steps"
    __table_args__ = (
        UniqueConstraint("plan_id", "step_key", name="uq_plan_steps_key"),
        UniqueConstraint("plan_id", "ordinal", name="uq_plan_steps_ordinal"),
        Index("ix_plan_steps_plan_status", "plan_id", "status"),
        Index("ix_plan_steps_linked_workflow", "linked_workflow_id"),
    )

    step_id: Mapped[UUID] = mapped_column("id", Uuid, primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("plans.id", ondelete="CASCADE"))
    step_key: Mapped[str] = mapped_column(String(64))
    ordinal: Mapped[int] = mapped_column(Integer)
    display_title: Mapped[str] = mapped_column(String(160))
    step_kind: Mapped[str] = mapped_column(
        String(20), default="CAPABILITY", server_default="CAPABILITY"
    )
    capability: Mapped[str | None] = mapped_column(String(40), nullable=True)
    condition_spec_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    condition_decision_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    guard_condition_step_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("plan_steps.id"), nullable=True, index=True
    )
    executor_kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30))
    subtask_query: Mapped[str | None] = mapped_column(String(500), nullable=True)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    linked_workflow_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("workflows.id"), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlanStepDependencyModel(Base):
    __tablename__ = "plan_step_dependencies"
    __table_args__ = (CheckConstraint("step_id <> depends_on_step_id", name="ck_plan_no_self"),)

    step_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("plan_steps.id", ondelete="CASCADE"), primary_key=True
    )
    depends_on_step_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("plan_steps.id", ondelete="CASCADE"), primary_key=True
    )


class PayeeModel(Base):
    __tablename__ = "payees"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "display_name", "bank_name", "account_fingerprint", name="uq_payee_identity"
        ),
        UniqueConstraint("user_id", "source_payee_id", name="uq_payee_source"),
    )
    payee_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    bank_name: Mapped[str] = mapped_column(String(100))
    account_suffix: Mapped[str] = mapped_column(String(4))
    account_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_payee_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    phone_alias: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RecurringTransferModel(Base):
    __tablename__ = "recurring_transfers"
    series_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    root_workflow_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("workflows.id"), unique=True)
    approval_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("approvals.id"))
    reauth_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("reauthentications.id"))
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    scope_hash: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ScheduledTransferModel(Base):
    __tablename__ = "scheduled_transfers"
    __table_args__ = (
        UniqueConstraint("series_id", "occurrence_index", name="uq_recurring_occurrence"),
    )
    series_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("recurring_transfers.series_id"), nullable=True, index=True
    )
    occurrence_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schedule_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    workflow_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("workflows.id"), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING_AUTHORIZATION")
    version: Mapped[int] = mapped_column(Integer, default=1)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execute_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    business_timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    authorization_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    operation_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("operations.id"), nullable=True, unique=True
    )
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)


class ScheduledAuthorizationModel(Base):
    __tablename__ = "scheduled_authorizations"
    authorization_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    schedule_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("scheduled_transfers.schedule_id"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(255))
    workflow_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("workflows.id"))
    approval_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("approvals.id"))
    reauth_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("reauthentications.id"))
    payload_hash: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MockSubscriptionStateModel(Base):
    __tablename__ = "mock_subscription_states"
    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    subscription_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    status: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer, default=1)
    next_billing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MockSubscriptionActionModel(Base):
    __tablename__ = "mock_subscription_actions"
    provider_reference: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    subscription_id: Mapped[str] = mapped_column(String(255), index=True)
    idempotency_key: Mapped[UUID] = mapped_column(Uuid, unique=True, index=True)
    action: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), index=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AARequestModel(Base):
    __tablename__ = "aa_requests"
    request_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    conversation_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("conversations.id"))
    source_task_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tasks.id"), unique=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    draft_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AAShareModel(Base):
    __tablename__ = "aa_shares"
    __table_args__ = (
        UniqueConstraint("request_id", "user_id", name="uq_aa_participant"),
        CheckConstraint("amount_cents > 0", name="ck_aa_positive_share"),
    )
    share_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    request_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("aa_requests.request_id"), index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    position: Mapped[int] = mapped_column(Integer)
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    workflow_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("workflows.id"), nullable=True, unique=True
    )
    operation_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("operations.id"), nullable=True, unique=True
    )


class NotificationModel(Base):
    __tablename__ = "notifications"
    kind: Mapped[str] = mapped_column(
        String(40), default="SCHEDULE_RESULT", server_default="SCHEDULE_RESULT"
    )
    notification_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    source_key: Mapped[str] = mapped_column(String(255), unique=True)
    title: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    schedule_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    anomaly_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class SubscriptionNotificationCursorModel(Base):
    __tablename__ = "subscription_notification_cursors"
    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    seen_transaction_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    last_billing_scan_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MockSubscriptionChargeModel(Base):
    __tablename__ = "mock_subscription_charges"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "subscription_id", "billing_at", name="uq_subscription_billing"
        ),
    )
    charge_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    subscription_id: Mapped[str] = mapped_column(String(255))
    source_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    merchant: Mapped[str] = mapped_column(String(100))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    billing_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    status: Mapped[str] = mapped_column(String(20))
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)

# Wealth mappings share the existing metadata (including SQLite test create_all).
from banking_api.wealth import models as wealth_models  # noqa: E402, F401
