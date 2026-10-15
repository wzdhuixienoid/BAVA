from banking_api.agent_skills import packaged_catalog
from banking_api.agents.models import AgentDefinition

_SKILL = packaged_catalog().activate_named("subscription-analysis")

SUBSCRIPTION_ANALYSIS_AGENT_ID = "agent:subscription-analysis"

SUBSCRIPTION_ANALYSIS_AGENT = AgentDefinition(
    agent_id=SUBSCRIPTION_ANALYSIS_AGENT_ID,
    instructions=_SKILL.instructions,
    skills=(_SKILL,),
    allowed_capabilities=frozenset({"subscription.analyze"}),
)
