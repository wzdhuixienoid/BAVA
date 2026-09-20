from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from banking_api.domain.message import Message


class Conversation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    conversation_id: UUID
    user_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationCreate(BaseModel):
    title: str = "新对话"


class ConversationDetail(Conversation):
    messages: list[Message]
