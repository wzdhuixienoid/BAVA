from typing import Any

from pydantic import BaseModel

from banking_api.domain.conversation import ConversationDetail
from banking_api.domain.task import Task


class ContextEnvelope(BaseModel):
    task: Task
    conversation: ConversationDetail
    memory: list[dict[str, Any]]
    upstream_results: list[dict[str, Any]]
    constraints: dict[str, Any]


class ContextBuilder:
    """Interface placeholder; no memory, RAG, prompts, or token budgeting in Iteration 0."""

    def build(self, *, task: Task, conversation: ConversationDetail) -> ContextEnvelope:
        return ContextEnvelope(
            task=task,
            conversation=conversation,
            memory=[],
            upstream_results=[],
            constraints={},
        )

