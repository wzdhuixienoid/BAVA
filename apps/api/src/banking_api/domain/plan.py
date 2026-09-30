from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from banking_api.planning.models import PlanCapability, PlanStatus, PlanStepStatus


class PlanStep(BaseModel):
    step_id: UUID
    step_key: str
    display_title: str
    capability: PlanCapability
    status: PlanStepStatus
    depends_on: list[UUID]
    linked_workflow_id: UUID | None
    result_summary: dict[str, Any] | None
    error_code: str | None
    rollback_allowed: bool


class Plan(BaseModel):
    plan_id: UUID
    conversation_id: UUID
    source_task_id: UUID
    goal_summary: str
    status: PlanStatus
    version: int
    manual_takeover: bool
    steps: list[PlanStep]
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class RollbackPlanAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_step_id: UUID
