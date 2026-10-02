from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from banking_api.financial.report_formatter import ReportFormatter

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


class PlanStepKind(StrEnum):
    CAPABILITY = "CAPABILITY"
    CONDITION = "CONDITION"


class ConditionPredicate(StrEnum):
    ACCOUNT_BALANCE_AT_LEAST = "ACCOUNT_BALANCE_AT_LEAST"
    MONTHLY_SPENDING_AT_LEAST = "MONTHLY_SPENDING_AT_LEAST"
    SUBSCRIPTION_MONTHLY_COST_AT_LEAST = "SUBSCRIPTION_MONTHLY_COST_AT_LEAST"


PREDICATE_SOURCES = {
    ConditionPredicate.ACCOUNT_BALANCE_AT_LEAST: PlanCapability.ACCOUNT_QUERY,
    ConditionPredicate.MONTHLY_SPENDING_AT_LEAST: PlanCapability.FINANCIAL_ANALYSIS,
    ConditionPredicate.SUBSCRIPTION_MONTHLY_COST_AT_LEAST: PlanCapability.SUBSCRIPTION_ANALYSIS,
}


class ConditionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    predicate: ConditionPredicate
    source_step_key: str = Field(min_length=1, max_length=64)
    threshold: str = Field(min_length=1, max_length=64)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    @field_validator("threshold")
    @classmethod
    def decimal_threshold(cls, value: str) -> str:
        try:
            amount = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("threshold must be a finite nonnegative Decimal string") from exc
        if not amount.is_finite() or amount < 0:
            raise ValueError("threshold must be a finite nonnegative Decimal string")
        return value


class ConditionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    predicate: ConditionPredicate
    source_step_id: UUID
    source_output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    actual_value: str
    threshold_value: str
    currency: str
    outcome: Literal["TRUE", "FALSE"]
    evaluated_at: datetime
    actual_display: str = ""
    threshold_display: str = ""

    @model_validator(mode="after")
    def format_display(self):
        formatter = ReportFormatter()
        object.__setattr__(
            self, "actual_display", formatter.money(Decimal(self.actual_value), self.currency)
        )
        object.__setattr__(
            self, "threshold_display", formatter.money(Decimal(self.threshold_value), self.currency)
        )
        return self


class StepProposalBase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    step_key: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z][a-zA-Z0-9_-]*$")
    display_title: str = Field(min_length=1, max_length=160)
    depends_on: list[str] = Field(max_length=MAX_PLAN_STEPS)


class CapabilityStepProposal(StepProposalBase):
    kind: Literal["CAPABILITY"]
    capability: PlanCapability
    subtask_query: str | None = Field(default=None, min_length=1, max_length=500)
    guard_condition_step_key: str | None = Field(default=None, min_length=1, max_length=64)


class ConditionStepProposal(StepProposalBase):
    kind: Literal["CONDITION"]
    condition: ConditionSpec


PlanStepProposal = Annotated[
    CapabilityStepProposal | ConditionStepProposal, Field(discriminator="kind")
]


class PlanProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    goal_summary: str = Field(min_length=1, max_length=500)
    steps: list[PlanStepProposal] = Field(min_length=2, max_length=MAX_PLAN_STEPS)


class ValidatedPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    proposal: PlanProposal
