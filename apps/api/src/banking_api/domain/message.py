from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from banking_api.domain.enums import MessageRole


class Message(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message_id: UUID
    conversation_id: UUID
    role: MessageRole
    content: str
    created_at: datetime


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)


class MessageAccepted(BaseModel):
    message_id: UUID
    task_id: UUID
    request_id: UUID

