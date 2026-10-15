from banking_api.agent_skills import packaged_catalog
from banking_api.skills.models import SkillDefinition


class SkillRegistry:
    def __init__(self) -> None:
        self._items: dict[str, SkillDefinition] = {}

    def register(self, skill: SkillDefinition) -> None:
        if skill.skill_id in self._items:
            raise ValueError(f"Skill already registered: {skill.skill_id}")
        packaged_catalog().bind_business_skill(skill)
        self._items[skill.skill_id] = skill

    def get(self, skill_id: str) -> SkillDefinition | None:
        return self._items.get(skill_id)

    def all(self) -> tuple[SkillDefinition, ...]:
        return tuple(self._items.values())
