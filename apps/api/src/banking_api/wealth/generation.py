"""HTTP orchestration uses the same semantic frame, facts and LangGraph contract."""

from uuid import uuid4

from banking_api.agent_skills import AgentSkillCatalog
from banking_api.agents.models import AgentDefinition
from banking_api.agents.wealth_advisor_agent import WEALTH_ADVISOR_AGENT
from banking_api.domain.enums import RuntimeBackend
from banking_api.runtime.base import AgentRunRequest
from banking_api.wealth.advisory import WealthAdvisoryService
from banking_api.wealth.answer import answer_prompt, apply_answer, initial_fact_calls
from banking_api.wealth.coordination import analysis_request
from banking_api.wealth.semantic import interpret


async def generate_analysis(service, body, principal, app):
    frame = await interpret(app.state.llm_provider, body.query or body.needs)
    if body.intent == "COMPARISON" and body.product_ids:
        frame.action = "COMPARE"
    elif body.intent == "EDUCATION":
        frame.action = "KNOWLEDGE"
    elif body.intent == "CATALOGUE":
        frame.action = "CATALOGUE"
    resolved = analysis_request(
        frame,
        await service.products(principal.user_id),
        accounts=service.balances._bank.list_accounts(user_id=principal.user_id),
    )
    if body.product_ids:
        resolved.product_ids = body.product_ids
    if body.amount:
        resolved.amount = body.amount
    if body.account_id:
        resolved.account_id = body.account_id
    analysis = await WealthAdvisoryService(service).analyze(principal.user_id, resolved)
    skill = AgentSkillCatalog().activate(frame.action, frame.source_text)
    try:
        runtime = app.state.runtime_factory.get(RuntimeBackend.LANGGRAPH)
    except ValueError:
        return apply_answer(analysis, "", skill)
    for _ in range(2):
        try:
            result = await runtime.run(
                AgentRunRequest(
                    task_id=uuid4(),
                    conversation_id=uuid4(),
                    current_task=frame.source_text
                    + (
                        "\n修复一次：" + str(analysis.validation_error)
                        if analysis.validation_error
                        else ""
                    ),
                    conversation_messages=[],
                    initial_tool_calls=initial_fact_calls(analysis),
                    principal=principal,
                    agent=AgentDefinition(
                        agent_id=WEALTH_ADVISOR_AGENT.agent_id,
                        allowed_capabilities=WEALTH_ADVISOR_AGENT.allowed_capabilities,
                        instructions=answer_prompt(analysis, skill),
                    ),
                )
            )
            analysis = apply_answer(analysis, result.answer, skill)
            if analysis.narrative_source == "MODEL_GENERATED":
                break
        except Exception:
            analysis = apply_answer(analysis, "", skill)
    return analysis
