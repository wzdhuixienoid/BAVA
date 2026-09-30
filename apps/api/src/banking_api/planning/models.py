from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

MAX_PLAN_STEPS = 8


class PlanCapability(StrEnum):
    ACCOUNT_QUERY = "ACCOUNT_QUERY"
    FINANCIAL_ANALYSIS = "FINANCIAL_ANALYSIS"
    SUBSCRIPTION_ANALYSIS = "SUBSCRIPTION_ANALYSIS"
    TRANSFER_WORKFLOW = "TRANSFER_WORKFLOW"
    SUBSCRIPTION_CANCEL_WORKFLOW = "SUBSCRIPTION_CANCEL_WORKFLOW"


class PlanStatus(StrEnum):
    RUNNING = "RUNNING"
    WAITING_USER = "WAITING_USER"
    WAITING_EXTERNAL = "WAITING_EXTERNAL"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PlanStepStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_USER = "WAITING_USER"
    WAITING_EXTERNAL = "WAITING_EXTERNAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"


class PlanStepProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    step_key: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z][a-zA-Z0-9_-]*$")
    display_title: str = Field(min_length=1, max_length=160)
    capability: PlanCapability
    depends_on: list[str] = Field(max_length=MAX_PLAN_STEPS)
    subtask_query: str | None = Field(default=None, min_length=1, max_length=500)


class PlanProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    goal_summary: str = Field(min_length=1, max_length=500)
    steps: list[PlanStepProposal] = Field(min_length=2, max_length=MAX_PLAN_STEPS)


class ValidatedPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal: PlanProposal
