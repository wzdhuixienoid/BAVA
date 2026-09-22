from typing import Any, TypedDict


class BankingAgentGraphState(TypedDict):
    task_id: str
    conversation_id: str
    agent_id: str
    runtime_messages: list[dict[str, Any]]
    step_count: int
    tool_call_count: int
    pending_tool_calls: list[dict[str, Any]]
    successful_tool_results: list[dict[str, Any]]
    final_answer: str | None
    error: dict[str, Any] | None
