from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from banking_api.domain.enums import WorkflowStatus


class WorkflowType(StrEnum):
    TRANSFER = "TRANSFER"


class Workflow(BaseModel):
    """Authoritative, user-owned persistent workflow resource."""

    model_config = ConfigDict(from_attributes=True)

    workflow_id: UUID
    user_id: str
    conversation_id: UUID
    source_task_id: UUID
    workflow_type: WorkflowType
    status: WorkflowStatus
    version: int
    state: dict[str, Any]
    created_at: datetime
    updated_at: datetime
