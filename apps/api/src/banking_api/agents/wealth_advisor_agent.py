from banking_api.agent_skills import packaged_catalog
from banking_api.agents.models import AgentDefinition
from banking_api.wealth.tools import CALLER, READS

_SKILL = packaged_catalog().activate_named(
    "wealth-advisory", references=("references/agent-rules.md", "references/evidence-and-facts.md")
)

WEALTH_ADVISOR_AGENT = AgentDefinition(
    agent_id=CALLER, allowed_capabilities=READS, instructions=_SKILL.instructions, skills=(_SKILL,)
)
