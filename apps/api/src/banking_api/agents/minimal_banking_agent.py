from banking_api.agent_skills import packaged_catalog
from banking_api.agents.models import AgentDefinition

_SKILL = packaged_catalog().activate_named("banking-assistance")

MINIMAL_BANKING_AGENT = AgentDefinition(
    agent_id="agent:minimal-banking",
    instructions=_SKILL.instructions,
    skills=(_SKILL,),
    allowed_capabilities=frozenset(
        {"account.list", "account.get_balance", "payee.list", "payee.search"}
    ),
)
