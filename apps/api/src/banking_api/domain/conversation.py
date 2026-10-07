from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=100)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("对话名称不能为空")
        if any(ord(character) < 32 for character in value):
            raise ValueError("对话名称不能包含控制字符")
        return value


class ConversationDetail(Conversation):
    messages: list[Message]
