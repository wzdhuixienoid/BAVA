"""One read-only banking agent with explicit, request-scoped skill profiles."""

from enum import StrEnum
from functools import lru_cache

from banking_api.agent_skills import packaged_catalog
from banking_api.agents.models import AgentDefinition

PERSONAL_BANKING_AGENT_ID = "agent:personal-banking"
ACCOUNT_CAPABILITIES = frozenset(
    {"account.list", "account.get_balance", "account.statement", "payee.list", "payee.search"}
)
SPENDING_CAPABILITIES = frozenset(
    {
        "account.list",
        "transaction.spending_summary",
        "transaction.category_breakdown",
        "transaction.compare_periods",
        "transaction.top_transactions",
        "transaction.detect_anomalies",
    }
)
LEGACY_AGENT_ROUTES = {
    "agent:minimal-banking": "ACCOUNT_QUERY",
    "agent:financial-analysis": "FINANCIAL_ANALYSIS",
}


class PersonalBankingMode(StrEnum):
    ACCOUNT = "ACCOUNT"
    SPENDING = "SPENDING"
    COMBINED = "COMBINED"


@lru_cache
def personal_banking_agent(mode: PersonalBankingMode, *, report: bool = False) -> AgentDefinition:
    skills = []
    capabilities = frozenset()
    if mode in {PersonalBankingMode.ACCOUNT, PersonalBankingMode.COMBINED}:
        skills.append(packaged_catalog().activate_named("banking-assistance"))
        capabilities |= ACCOUNT_CAPABILITIES
    if mode in {PersonalBankingMode.SPENDING, PersonalBankingMode.COMBINED}:
        references = ("references/analysis-rules.md",) + (
            ("references/report-source.md",) if report else ()
        )
        skills.append(
            packaged_catalog().activate_named("financial-analysis", references=references)
        )
        capabilities |= SPENDING_CAPABILITIES
    instructions = "\n\n".join(s.instructions for s in skills)
    if mode is PersonalBankingMode.COMBINED:
        instructions += (
            "\n本次同时处理账户查询和消费分析，请完成用户明确要求的两部分。"
            "基础查询成功不代表组合任务完成。消费分析必须查询 get_spending_summary，"
            "分类需求还须查询 get_category_breakdown；只查分类不能替代汇总。"
            "只询问异常检查时遵循异常规则，不强加消费汇总。"
            "复用已查到的账户列表，余额按所需账户查询，可同轮查询多个账户。"
            "当前余额与期间收入减支出含义不同，不把两者混用；缺少后端合计时逐账户展示。"
            "未要求查询收款人时不调用收款人工具。报告任务也应保留已查询的账户余额。"
        )
    return AgentDefinition(
        agent_id=PERSONAL_BANKING_AGENT_ID,
        instructions=instructions,
        allowed_capabilities=capabilities,
        skills=tuple(skills),
    )


def uses_financial_analysis(agent: AgentDefinition) -> bool:
    return any(c.startswith("transaction.") for c in agent.allowed_capabilities)


PERSONAL_BANKING_ACCOUNT_AGENT = personal_banking_agent(PersonalBankingMode.ACCOUNT)
PERSONAL_BANKING_SPENDING_AGENT = personal_banking_agent(PersonalBankingMode.SPENDING)
# Registry capability envelope. Each execution selects an explicit profile before calling the model.
PERSONAL_BANKING_AGENT = personal_banking_agent(PersonalBankingMode.COMBINED)
