from typing import Any


class AgentRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Any] = {}

    def register(self, agent_id: str, agent: Any) -> None:
        if agent_id in self._items:
            raise ValueError(f"Agent already registered: {agent_id}")
        self._items[agent_id] = agent

    def get(self, agent_id: str) -> Any | None:
        return self._items.get(agent_id)

