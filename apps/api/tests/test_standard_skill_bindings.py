"""All production agents and business implementations use real standard packages."""

import json
import subprocess
import sys
from dataclasses import replace
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from test_agent_runtime import build_runtime, run_runtime
from test_anomaly_skill import sample_snapshot
from test_monthly_spending_report_skill import golden_snapshot
from test_wealth import wealth as wealth
from test_wealth_v0113 import result

from banking_api.agent_skills import AgentSkillCatalog, packaged_catalog
from banking_api.agents.financial_analysis_agent import FINANCIAL_ANALYSIS_AGENT
from banking_api.agents.minimal_banking_agent import MINIMAL_BANKING_AGENT
from banking_api.agents.models import AgentDefinition
from banking_api.agents.subscription_analysis_agent import SUBSCRIPTION_ANALYSIS_AGENT
from banking_api.agents.wealth_advisor_agent import WEALTH_ADVISOR_AGENT
from banking_api.context.builder import ContextBuilder
from banking_api.domain.principal import ExecutionPrincipal
from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.llm.models import LLMResponse
from banking_api.policy.service import PolicyService
from banking_api.registries.agent_registry import AgentRegistry
from banking_api.registries.skill_registry import SkillRegistry
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.runtime.base import AgentRunRequest, AgentRuntimeError
from banking_api.runtime.langgraph.graph import LangGraphAgentRuntime
from banking_api.runtime.manual_agent_runtime import ManualAgentRuntime
from banking_api.runtime.task_runner import InProcessTaskRunner
from banking_api.skills.monthly_spending_report import MonthlySpendingReportSkill
from banking_api.skills.transaction_anomaly_analysis import TransactionAnomalyAnalysisSkill
from banking_api.skills.wealth_recommendation import WealthRecommendationSkill
from banking_api.tools.executor import ToolExecutor

AGENTS = (
    MINIMAL_BANKING_AGENT,
    FINANCIAL_ANALYSIS_AGENT,
    SUBSCRIPTION_ANALYSIS_AGENT,
    WEALTH_ADVISOR_AGENT,
)
BUSINESS = (MonthlySpendingReportSkill, TransactionAnomalyAnalysisSkill, WealthRecommendationSkill)


@pytest.mark.parametrize("agent", AGENTS, ids=lambda a: a.agent_id)
async def test_graph_sends_real_skill_instructions_and_records_actual_hashes(agent):
    provider = FakeLLMProvider([LLMResponse(content="请明确要查询的范围。")])
    registry = ToolRegistry()
    runtime = LangGraphAgentRuntime(
        provider=provider,
        registry=registry,
        executor=ToolExecutor(registry, PolicyService()),
        context_builder=ContextBuilder(),
        checkpointer=InMemorySaver(),
    )
    events = []

    async def sink(event, data):
        events.append((event, data))

    await runtime.run(
        AgentRunRequest(
            task_id=uuid4(),
            conversation_id=uuid4(),
            current_task="请帮助查询",
            conversation_messages=[],
            principal=ExecutionPrincipal.for_task("dev-user-001"),
            agent=agent,
            event_sink=sink,
        )
    )
    assert provider.requests
    instructions = provider.requests[0].messages[0].content
    for skill in agent.skills:
        packaged_catalog().validate_activation(skill)
        assert skill.instructions in instructions
    started = next(data for name, data in events if name == "agent.run.started")
    assert started["skills"] == [s.metadata() for s in agent.skills]
    assert all(s["resource_hashes"] for s in started["skills"])


async def test_manual_runtime_uses_same_standard_package():
    runtime, provider = build_runtime([LLMResponse(content="请明确需要查询的账户。")])
    _, events = await run_runtime(runtime)
    assert MINIMAL_BANKING_AGENT.skills[0].instructions in provider.requests[0].messages[0].content
    started = next(data for name, data in events if name == "agent.run.started")
    assert started["skills"][0]["skill_id"] == "banking-assistance"


@pytest.mark.parametrize("implementation", BUSINESS, ids=lambda c: c.definition.skill_id)
def test_business_implementation_is_bound_to_standard_contract_and_helper(implementation):
    skill = implementation()
    assert skill.active_skill.skill_id == implementation.definition.agent_skill_name
    assert "scripts/run.py" in skill.active_skill.resources
    packaged_catalog().validate_activation(skill.active_skill)
    assert skill.definition.allowed_tools == ()


def test_registry_rejects_agents_without_real_skill_instructions():
    registry = AgentRegistry()
    with pytest.raises(ValueError):
        registry.register(AgentDefinition("agent:no-skill", "free prompt", frozenset()))
    with pytest.raises(ValueError):
        registry.register(replace(MINIMAL_BANKING_AGENT, instructions="unrelated instructions"))
    fake_skill = replace(MINIMAL_BANKING_AGENT.skills[0], resources={"SKILL.md": "fake"})
    with pytest.raises(ValueError):
        registry.register(replace(MINIMAL_BANKING_AGENT, skills=(fake_skill,)))


@pytest.mark.parametrize(
    "changes",
    [
        {"agent_skill_name": ""},
        {"agent_skill_name": "wealth-advisory"},
        {"version": 2},
        {"input_schema": AgentDefinition},
        {"allowed_tools": ("bank.transfer",)},
    ],
)
def test_registry_rejects_business_contract_or_permission_mismatch(changes):
    with pytest.raises(ValueError):
        SkillRegistry().register(replace(MonthlySpendingReportSkill.definition, **changes))


def run_helper(name, snapshot, *args):
    path = AgentSkillCatalog().root / name / "scripts/run.py"
    return subprocess.run(
        [sys.executable, str(path), *args],
        input=snapshot,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


def test_monthly_helper_preserves_golden_numbers_without_narrative():
    process = run_helper("monthly-spending-report", golden_snapshot().model_dump_json())
    assert process.returncode == 0, process.stderr
    report = json.loads(process.stdout)
    assert report["overview"]["total_spending"] == "16547.30"
    assert report["overview"]["total_income"] == "23800.00"
    assert report["category_breakdown"][0]["category"] == "HOUSING"
    assert "insights" not in report


@pytest.mark.parametrize("review", [False, True])
def test_anomaly_helper_preserves_detected_evidence_and_supports_review(review):
    process = run_helper(
        "transaction-anomaly-analysis",
        sample_snapshot().model_dump_json(),
        *(["--review"] if review else []),
    )
    assert process.returncode == 0, process.stderr
    output = json.loads(process.stdout)
    assert "8600.00" in output["answer"]
    assert "欺诈" in output["answer"]
    if review:
        assert output["items"][0]["transaction_id"] == "spike"


async def test_wealth_helper_uses_redemption_units_and_known_fields(wealth):
    analysis = await result(wealth, "用工资卡赎回演示均衡优选10份")
    process = run_helper("wealth-recommendation", analysis.model_dump_json())
    assert process.returncode == 0, process.stderr
    output = json.loads(process.stdout)
    assert output["questions"] == []
    assert output["budget_display"] is None
    assert "赎回份额" in output["headline"]


@pytest.mark.parametrize("name", [c.definition.agent_skill_name for c in BUSINESS])
def test_helpers_reject_incomplete_snapshots_with_no_output(name):
    process = run_helper(name, "{}")
    assert process.returncode == 2
    assert process.stdout == ""
    assert "Invalid" in process.stderr


def test_report_source_loads_extra_reference_only_for_explicit_report_mode():
    base = FINANCIAL_ANALYSIS_AGENT
    derived = InProcessTaskRunner._report_source_agent(base)
    assert "references/report-source.md" not in base.skills[0].resources
    assert "references/report-source.md" in derived.skills[0].resources
    assert derived.allowed_capabilities == base.allowed_capabilities
    assert "必须成功获取 spending_summary 和 category_breakdown" in derived.instructions
    packaged_catalog().validate_activation(derived.skills[0])


def test_named_activation_does_not_load_mode_references_implicitly():
    skill = packaged_catalog().activate_named("financial-analysis")
    assert set(skill.resources) == {"SKILL.md"}
    assert "必须成功获取 spending_summary 和 category_breakdown" not in skill.instructions


@pytest.mark.parametrize("backend", ["manual", "langgraph"])
async def test_runtime_rejects_unbound_agents_before_model_or_tool_access(backend):
    agent = AgentDefinition("agent:unbound", "free prompt", frozenset())
    provider = FakeLLMProvider([LLMResponse(content="should not run")])
    registry = ToolRegistry()
    common = dict(
        provider=provider,
        registry=registry,
        executor=ToolExecutor(registry, PolicyService()),
        context_builder=ContextBuilder(),
    )
    runtime = (
        ManualAgentRuntime(**common, agent=agent)
        if backend == "manual"
        else (LangGraphAgentRuntime(**common, checkpointer=InMemorySaver()))
    )
    request = AgentRunRequest(
        task_id=uuid4(),
        conversation_id=uuid4(),
        current_task="查询账户",
        conversation_messages=[],
        agent=agent,
        principal=ExecutionPrincipal.for_task("dev-user-001"),
    )
    with pytest.raises(AgentRuntimeError) as captured:
        await runtime.run(request)
    assert captured.value.code == "AGENT_SKILL_BINDING_INVALID"
    assert provider.requests == []
