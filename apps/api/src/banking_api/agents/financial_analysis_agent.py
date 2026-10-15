from banking_api.agent_skills import packaged_catalog
from banking_api.agents.models import AgentDefinition

_SKILL = packaged_catalog().activate_named(
    "financial-analysis", references=("references/analysis-rules.md",)
)

FINANCIAL_ANALYSIS_AGENT_ID = "agent:financial-analysis"

FINANCIAL_ANALYSIS_AGENT = AgentDefinition(
    agent_id=FINANCIAL_ANALYSIS_AGENT_ID,
    instructions=_SKILL.instructions,
    skills=(_SKILL,),
    allowed_capabilities=frozenset(
        {
            "account.list",
            "transaction.spending_summary",
            "transaction.category_breakdown",
            "transaction.compare_periods",
            "transaction.top_transactions",
            "transaction.detect_anomalies",
        }
    ),
)
