from typing import Any


class SkillRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Any] = {}

    def register(self, skill_id: str, skill: Any) -> None:
        if skill_id in self._items:
            raise ValueError(f"Skill already registered: {skill_id}")
        self._items[skill_id] = skill

    def get(self, skill_id: str) -> Any | None:
        return self._items.get(skill_id)

