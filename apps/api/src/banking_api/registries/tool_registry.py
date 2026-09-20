from banking_api.tools.models import ToolSpec


class ToolRegistry:
    def __init__(self) -> None:
        self._by_capability: dict[str, ToolSpec] = {}
        self._by_name: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.capability_id in self._by_capability or spec.name in self._by_name:
            raise ValueError(f"Tool already registered: {spec.capability_id}/{spec.name}")
        self._by_capability[spec.capability_id] = spec
        self._by_name[spec.name] = spec

    def get(self, capability_id: str) -> ToolSpec | None:
        return self._by_capability.get(capability_id)

    def get_by_name(self, name: str) -> ToolSpec | None:
        return self._by_name.get(name)

    def resolve(self, capability_ids: frozenset[str]) -> list[ToolSpec]:
        return [
            spec
            for spec in self._by_capability.values()
            if spec.capability_id in capability_ids
        ]

    def all(self) -> tuple[ToolSpec, ...]:
        return tuple(self._by_capability.values())
