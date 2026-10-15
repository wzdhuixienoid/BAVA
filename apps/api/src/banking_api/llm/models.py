from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class LLMToolCall(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    arguments: Any = Field(default_factory=dict)


class LLMMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[LLMToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    reasoning_content: str | None = None


class LLMToolDefinition(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    description: str
    input_schema: dict[str, Any]


class LLMRequest(BaseModel):
    messages: list[LLMMessage]
    tools: list[LLMToolDefinition] = Field(default_factory=list)


class LLMUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMResponse(BaseModel):
    reasoning_content: str | None = None
    content: str | None = None
    tool_calls: list[LLMToolCall] = Field(default_factory=list)
    usage: LLMUsage = Field(default_factory=LLMUsage)
    finish_reason: str | None = None

    @model_validator(mode="after")
    def unique_tool_call_ids(self):
        if len({call.id for call in self.tool_calls}) != len(self.tool_calls):
            raise ValueError("Tool call IDs must be unique within a response")
        return self
