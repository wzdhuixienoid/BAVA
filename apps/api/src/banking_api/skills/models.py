from dataclasses import dataclass

from pydantic import BaseModel


@dataclass(frozen=True)
class SkillDefinition:
    skill_id: str
    version: int
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    allowed_tools: tuple[str, ...] = ()
    agent_skill_name: str = ""
