from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Event(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: UUID
    event_type: str
    timestamp: datetime
    conversation_id: UUID
    task_id: UUID | None
    sequence: int
    data: dict[str, Any]

