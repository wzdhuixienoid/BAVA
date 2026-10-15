from dataclasses import dataclass

from banking_api.agent_skills import ActivatedSkill, packaged_catalog


@dataclass(frozen=True)
class AgentDefinition:
    agent_id: str
    instructions: str
    allowed_capabilities: frozenset[str]
    skills: tuple[ActivatedSkill, ...] = ()

    def validate_skills(self) -> None:
        if not self.skills:
            raise ValueError("Agents require activated standard skill packages")
        for skill in self.skills:
            packaged_catalog().validate_activation(skill)
            if skill.instructions not in self.instructions:
                raise ValueError("Agents must use their bound skill instructions")
