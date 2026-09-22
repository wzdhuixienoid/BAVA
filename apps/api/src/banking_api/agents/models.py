from dataclasses import dataclass


@dataclass(frozen=True)
class AgentDefinition:
    agent_id: str
    instructions: str
    allowed_capabilities: frozenset[str]
