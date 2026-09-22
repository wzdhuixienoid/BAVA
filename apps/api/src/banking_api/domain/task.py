from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from banking_api.domain.enums import RuntimeBackend, TaskStatus


class Task(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: UUID
    conversation_id: UUID
    task_type: str
    runtime_backend: RuntimeBackend
    status: TaskStatus
    input: dict[str, Any]
    output: dict[str, Any] | None
    error: dict[str, Any] | None
    progress_message: str | None
    version: int
    created_at: datetime
    updated_at: datetime
