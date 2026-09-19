from dataclasses import dataclass

from banking_api.domain.enums import RiskLevel


@dataclass(frozen=True)
class ToolMetadata:
    capability_id: str
    name: str
    risk_level: RiskLevel
    side_effect: bool
    allowed_callers: frozenset[str]


class ToolRegistry:
    """Default-empty registry; Iteration 0 registers no write capabilities."""

    def __init__(self) -> None:
        self._items: dict[str, ToolMetadata] = {}

    def register(self, metadata: ToolMetadata) -> None:
        if metadata.capability_id in self._items:
            raise ValueError(f"Tool already registered: {metadata.capability_id}")
        self._items[metadata.capability_id] = metadata

    def get(self, capability_id: str) -> ToolMetadata | None:
        return self._items.get(capability_id)

