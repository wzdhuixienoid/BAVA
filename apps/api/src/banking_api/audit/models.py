"""Bounded, credential-free evidence DTOs; never an LLM input/output model."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from banking_api.domain.risk import TransferRiskDecision
from banking_api.planning.models import ConditionDecision


class AuditActor(StrEnum):
    USER = "USER"
    SYSTEM = "SYSTEM"
    AGENT = "AGENT"
    WORKFLOW = "WORKFLOW"
    SECURITY_GUARD = "SECURITY_GUARD"
    PROVIDER = "PROVIDER"
    RECOVERY_WORKER = "RECOVERY_WORKER"


class AuditFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(max_length=64)
    label: str = Field(max_length=80)
    value: str = Field(max_length=500)


class AuditEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID
    sequence: int
    timestamp: datetime
    category: str
    event_type: str
    actor_type: AuditActor
    resource_type: str
    resource_id: UUID
    status: str | None = None
    decision_summary: str
    related_resource_ids: dict[str, UUID] = Field(default_factory=dict)
    facts: list[AuditFact] = Field(default_factory=list, max_length=40)
    risk_decision: TransferRiskDecision | None = None
    condition_decision: ConditionDecision | None = None


class AuditResource(BaseModel):
    """Explicit current resource snapshot, separate from immutable historical events."""

    resource_type: str
    resource_id: UUID
    status: str
    facts: list[AuditFact] = Field(max_length=40)


class AuditWriteEvidence(BaseModel):
    workflow_count: int = Field(ge=0)
    approval_count: int = Field(ge=0)
    operation_count: int = Field(ge=0)
    provider_ledger_count: int = Field(ge=0)
    provider_submission_count: int = Field(ge=0)
    skipped_write_step_ids: list[UUID] = Field(max_length=8)
    business_success: bool
    no_write_started: bool


class AuditTrace(BaseModel):
    trace_id: UUID
    source_task_id: UUID
    generated_at: datetime
    task_status: str
    entries: list[AuditEntry] = Field(max_length=1000)
    resources: list[AuditResource] = Field(max_length=100)
    write_evidence: AuditWriteEvidence
    history_truncated: bool
    history_note: str
