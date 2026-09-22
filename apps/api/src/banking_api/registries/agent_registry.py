from banking_api.agents.models import AgentDefinition


class AgentRegistry:
    def __init__(self) -> None:
        self._items: dict[str, AgentDefinition] = {}

    def register(self, agent: AgentDefinition) -> None:
        if agent.agent_id in self._items:
            raise ValueError(f"Agent already registered: {agent.agent_id}")
        self._items[agent.agent_id] = agent

    def get(self, agent_id: str) -> AgentDefinition | None:
        return self._items.get(agent_id)

    def all(self) -> tuple[AgentDefinition, ...]:
        return tuple(self._items.values())
