"""Real-model intent and generated-answer evaluation on an isolated SQLite database."""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api/src"))
os.environ.update(
    APP_ENVIRONMENT="test", MOCK_WEALTH_ENABLED="true", AUTH_MODE="development"
)

from banking_api.agent_skills import packaged_catalog
from banking_api.agents.models import AgentDefinition
from banking_api.agents.wealth_advisor_agent import WEALTH_ADVISOR_AGENT
from banking_api.config.settings import get_settings
from banking_api.context.builder import ContextBuilder
from banking_api.domain.principal import ExecutionPrincipal
from banking_api.llm.openai_compatible_provider import OpenAICompatibleProvider
from banking_api.persistence.database import Base
from banking_api.runtime.base import AgentRunRequest, AgentRuntimeError
from banking_api.runtime.langgraph.graph import LangGraphAgentRuntime
from banking_api.wealth.advisory import WealthAdvisoryService
from banking_api.wealth.answer import answer_prompt, apply_answer, initial_fact_calls
from banking_api.wealth.calculation import CN
from banking_api.wealth.catalog import seed_catalog
from banking_api.wealth.coordination import analysis_request
from banking_api.wealth.schemas import AssessmentInput
from banking_api.wealth.semantic import interpret
from banking_api.wealth.service import WealthService
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def run(args):
    if "test" not in args.database.name:
        raise ValueError("test database required")
    settings = get_settings()
    provider = OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    engine = create_async_engine(f"sqlite+aiosqlite:///{args.database.resolve()}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from banking_api import main

    main.session_factory = factory
    app = main.create_app()
    clock = lambda: datetime(2026, 10, 12 if args.strategy else 11, 10, tzinfo=CN)
    app.state.wealth_provider.clock = clock
    balances = app.state.transfer_provider.balances
    async with factory() as session:
        await seed_catalog(session)
        if not args.unassessed:
            await WealthService(session, balances, clock).save_assessment(
                "dev-user-001",
                AssessmentInput(questionnaire_version="mock-v1", answers=[4] * 8),
            )
        await session.commit()
    runtime = LangGraphAgentRuntime(
        provider=provider,
        registry=app.state.tool_registry,
        executor=app.state.transfer_workflow_engine._executor,
        context_builder=ContextBuilder(),
        checkpointer=InMemorySaver(),
    )
    records = []
    semaphore = asyncio.Semaphore(2)

    async def expression(row):
        async with semaphore:
            frame = await interpret(provider, row["text"])
            money = [
                q
                for q in frame.quantity_mentions
                if q.unit == "元" and q.role != "RESERVE" and q.exact and not q.error
            ]
            amount = money[0].value if len(money) == 1 else None
            ok = frame.action == row["action"] and amount == row["amount"]
            record = {
                **row,
                "actual_action": frame.action,
                "actual_amount": amount,
                "source": frame.generation_source,
                "passed": ok,
                "frame": frame.model_dump(mode="json"),
            }
            records.append(record)
            print(row["id"], ok, frame.action, amount, flush=True)

    rows = json.loads(
        Path("apps/api/tests/data/wealth_v0113_expressions.json").read_text()
    )
    if not args.answers_only:
        await asyncio.gather(*(expression(r) for r in rows))
    args.output.write_text(
        json.dumps(
            {"model": settings.llm_model, "expressions": records},
            ensure_ascii=False,
            indent=2,
        )
    )
    scenes = [
        "我预算5千，想要赚钱，可接受部分亏损，有什么适合我的产品吗",
        "为什么第一款",
        "和第二款比呢",
        "我要买第二款",
        "用工资卡，买三千元",
        "比较演示均衡优选和演示均衡周享",
        "投0.5万，费用差多少",
        "每天开放是不是马上拿钱",
        "不能亏本金",
        "改一下，我可以承担部分本金损失，最多10%",
        "什么是最大回撤",
        "不要进取，只看R2以下，预算五千元",
        "请介绍目前在售的模拟理财",
    ]
    if args.independent:
        scenes = [
            "我预算五千元，希望有点收益，能接受少量亏损，推荐什么？",
            "我有5k，半年左右不用，先看看稳健一点的理财",
            "比较演示均衡优选和演示均衡周享，投0.5万元手续费差多少？",
            "为什么推荐演示稳享日日，它有什么代价？",
            "我必须保本，不能亏本金，想看看有哪些推荐",
            "最多愿意承受10%亏损，收益优先，能推荐吗？",
            "下周可能用到钱，预算￥5,000，可以买周开放理财吗？",
            "我要购买演示均衡优选",
            "用工资卡购买演示均衡优选三千五百元",
            "什么是最大回撤，低风险是否保证不亏？",
            "只看R2以下，不要进取，预算五千元",
            "介绍现在有哪些模拟理财产品",
        ]
    if args.strategy:
        scenes = [
            "我预算5千，想要赚钱，可接受部分亏损，有什么适合我的产品吗",
            "还有其他产品推荐吗，这些产品的收益太低了",
            "你对每个产品的定位是什么？",
            "比较演示进取成长和演示高波动精选，策略、收益来源和风险有什么区别？",
            "我不要这么大的波动，只看R2以下，有什么适合我的？",
        ]
    if args.scene:
        scenes = args.scene
    previous = None
    generated = []
    for text in scenes:
        if args.independent:
            previous = None
        frame = await interpret(provider, text, previous)
        async with factory() as session:
            svc = WealthService(session, balances, clock)
            body = analysis_request(
                frame,
                await svc.products("dev-user-001"),
                previous,
                balances._bank.list_accounts(user_id="dev-user-001"),
            )
            analysis = await WealthAdvisoryService(svc).analyze(
                "dev-user-001", body, previous
            )
        skill = packaged_catalog().activate(frame.action, text)
        events = []

        async def sink(event, data, events=events):
            events.append({"event": event, "data": data})

        error = None
        attempts = []
        for attempt in range(2):
            try:
                output = await runtime.run(
                    AgentRunRequest(
                        task_id=uuid4(),
                        conversation_id=uuid4(),
                        current_task=text
                        + (
                            "\n修复一次：" + str(analysis.validation_error)
                            if analysis.validation_error
                            else ""
                        ),
                        conversation_messages=[],
                        principal=ExecutionPrincipal.for_task("dev-user-001"),
                        agent=AgentDefinition(
                            agent_id=WEALTH_ADVISOR_AGENT.agent_id,
                            allowed_capabilities=WEALTH_ADVISOR_AGENT.allowed_capabilities,
                            instructions=answer_prompt(analysis, skill),
                            skills=(skill,),
                        ),
                        initial_tool_calls=initial_fact_calls(analysis),
                        event_sink=sink,
                    )
                )
                raw = output.answer
                analysis = apply_answer(analysis, raw, skill, model=settings.llm_model)
                attempts.append(
                    {"raw": raw, "validation_error": analysis.validation_error}
                )
                if analysis.answer.generation_source == "MODEL_GENERATED":
                    break
            except (ValueError, TimeoutError, RuntimeError, AgentRuntimeError) as exc:
                error = type(exc).__name__
                attempts.append({"runtime_error": error})
                raw = ""
                analysis = apply_answer(analysis, raw, skill, model=settings.llm_model)
        generated.append(
            {
                "text": text,
                "analysis": analysis.model_dump(mode="json"),
                "raw": raw,
                "events": events,
                "error": error,
                "attempts": attempts,
            }
        )
        print(
            "ANSWER",
            text,
            analysis.answer.generation_source,
            analysis.status,
            flush=True,
        )
        if frame.action != "KNOWLEDGE":
            previous = analysis
        args.output.write_text(
            json.dumps(
                {
                    "model": settings.llm_model,
                    "expressions": records,
                    "answers": generated,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--independent", action="store_true")
    parser.add_argument("--answers-only", action="store_true")
    parser.add_argument(
        "--strategy", action="store_true", help="Evaluate the v0.11.4 dialogue"
    )
    parser.add_argument("--scene", action="append", help="Evaluate a selected message")
    parser.add_argument(
        "--unassessed", action="store_true", help="Do not seed a risk assessment"
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
