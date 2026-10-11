from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from typing_extensions import TypedDict

from banking_api.domain.account import AccountQueryResults
from banking_api.domain.enums import (
    ExecutorType,
    RequestedOutput,
    RuntimeBackend,
    TaskStatus,
)
from banking_api.financial.report_models import MonthlySpendingReportCore
from banking_api.wealth.schemas import WealthAnalysis, WealthReadResult


class TaskOutput(TypedDict, total=False):
    # Keep existing result keys without refactoring unrelated snapshots or workflows.
    __pydantic_config__ = ConfigDict(extra="allow")

    wealth_analysis: WealthAnalysis
    wealth_results: list[WealthReadResult]
    wealth_final_result_index: int
    account_results: AccountQueryResults
    financial_display: MonthlySpendingReportCore


class Task(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: UUID
    conversation_id: UUID
    task_type: str
    runtime_backend: RuntimeBackend
    executor_type: ExecutorType | None
    executor_id: str | None
    requested_output: RequestedOutput | None
    status: TaskStatus
    input: dict[str, Any]
    output: TaskOutput | None
    error: dict[str, Any] | None
    progress_message: str | None
    version: int
    created_at: datetime
    updated_at: datetime
