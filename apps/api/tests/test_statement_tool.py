"""Public conversation queries must use the same posted cash facts as the dashboard."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from test_personal_banking_integration import interact
from test_routing_integration import call, route_response
from test_runtime_parity import build_runtime, request
from test_tool_contract_audit import execute_spec

from banking_api.application.account_statement_service import AccountStatementService
from banking_api.domain.statement import AccountStatementInput
from banking_api.domain.statement_scope import statement_arguments
from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.llm.models import LLMResponse
from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import (
    MockBankTransferModel,
    MockSubscriptionChargeModel,
    PayeeModel,
    TaskModel,
)
from banking_api.routing.models import RequestRoute
from banking_api.routing.request_router import RequestRouter
from banking_api.tools.banking import build_get_account_statement_tool

USER = "dev-user-001"
NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)


async def seed(app):
    async with app.state.test_session_factory() as session:
        session.add(
            PayeeModel(
                payee_id="deleted-recipient",
                user_id=USER,
                display_name="历史收款人",
                bank_name="虚构银行",
                account_suffix="1234",
                deleted_at=NOW,
            )
        )
        for identity, owner, destination, status, age in [
            ("outgoing", USER, None, "SUCCEEDED", 2),
            ("incoming", "sender", USER, "SUCCEEDED", 1),
            ("pending", USER, None, "PENDING", 3),
            ("failed", USER, None, "FAILED", 4),
            ("foreign", "someone-else", None, "SUCCEEDED", 5),
            ("old", USER, None, "SUCCEEDED", 40),
            ("future", USER, None, "SUCCEEDED", -1),
        ]:
            when = NOW - timedelta(days=age)
            session.add(
                MockBankTransferModel(
                    provider_reference=identity,
                    idempotency_key=uuid4(),
                    user_id=owner,
                    source_account_id="acc_salary",
                    payee_id="deleted-recipient",
                    amount=Decimal("123.45"),
                    currency="CNY",
                    status=status,
                    destination_user_id=destination,
                    destination_account_id="acc_savings" if destination else None,
                    credited_at=when if destination else None,
                    applied_at=when,
                    created_at=when,
                )
            )
        await session.commit()


@pytest.mark.parametrize(
    "prompt",
    [
        "我最近有哪些转账",
        "查询最近30天转账记录",
        "查看工资卡的购物明细",
        "查询今年订阅扣费记录",
        "最近理财资金流水",
        "查看上月转入记录",
        "分析我最近的转账记录，按收款人统计总额",
        "最近转账一共多少钱",
        "给张三转过多少钱",
    ],
)
async def test_history_queries_cannot_start_workflow_even_without_router_model(prompt):
    provider = FakeLLMProvider([])
    decision = await RequestRouter(provider).route(prompt)
    assert decision.route == RequestRoute.ACCOUNT_QUERY
    assert not provider.requests


@pytest.mark.parametrize(
    "prompt",
    [
        "查询转账记录，再给张三转100元",
        "给张三转100元，再查询转账记录",
        "查账单流水，然后从工资卡转账100元",
        "查转账历史并取消星幕视频订阅",
    ],
)
async def test_history_plus_new_mutation_is_not_silently_reduced_to_a_read(prompt):
    provider = FakeLLMProvider([route_response("ACCOUNT_QUERY")])
    assert (await RequestRouter(provider).route(prompt)).route == RequestRoute.COMPLEX_PLAN


async def test_posted_transfers_have_direction_owner_names_stable_pages_and_no_side_effect(
    app, monkeypatch
):
    await seed(app)
    monkeypatch.setattr(
        "banking_api.tools.banking.get_account_statement.reference_now", lambda: NOW
    )
    spec = build_get_account_statement_tool(MockBankService(), app.state.test_session_factory)
    result = await execute_spec(spec, {"category": "TRANSFER", "limit": 1})
    assert result.ok, result.error
    page = result.output
    assert page["total_count"] == 2 and page["next_offset"] == 1
    first = page["transactions"][0]
    assert first["direction"] == "CREDIT" and first["amount_display"] == "+¥123.45"
    assert "储蓄卡" in first["account_display"] and first["status"] == "POSTED"
    following = await execute_spec(
        spec, {"category": "TRANSFER", "limit": 1, "offset": 1, "as_of": page["as_of"]}
    )
    assert following.ok, following.error
    second = following.output["transactions"][0]
    assert second["merchant"] == "历史收款人" and second["amount_display"] == "-¥123.45"
    assert following.output["next_offset"] is None
    filtered = await execute_spec(
        spec,
        {
            "category": "TRANSFER",
            "direction": "DEBIT",
            "query": "历史收款人",
            "account_ids": ["acc_salary"],
        },
    )
    assert filtered.ok and filtered.output["total_count"] == 1
    async with app.state.test_session_factory() as session:
        rows = (
            await AccountStatementService(MockBankService(), session).page(
                user_id=USER, as_of=NOW, category="TRANSFER"
            )
        ).transactions
        assert {first["transaction_id"], second["transaction_id"]} <= {
            r.transaction_id for r in rows
        }
        pending = await session.get(MockBankTransferModel, "pending")
        assert pending.status == "PENDING"
        assert await session.scalar(select(func.count()).select_from(MockBankTransferModel)) == 7
        foreign = await AccountStatementService(MockBankService(), session).query(
            user_id="unrelated", arguments=AccountStatementInput(), now=NOW
        )
        assert foreign.transactions == []
    denied = await execute_spec(spec, {"account_ids": ["foreign-account"]})
    assert not denied.ok and denied.error.code == "ACCOUNT_NOT_FOUND"


async def test_calendar_month_uses_beijing_and_exact_date_range(app):
    when = datetime(2025, 12, 31, 16, tzinfo=UTC)
    async with app.state.test_session_factory() as session:
        session.add(
            MockSubscriptionChargeModel(
                user_id=USER,
                subscription_id="boundary",
                source_account_id="acc_salary",
                merchant="跨年订阅",
                amount=Decimal("28"),
                currency="CNY",
                billing_at=when,
                created_at=when,
                status="SUCCEEDED",
            )
        )
        await session.commit()
        service = AccountStatementService(MockBankService(), session)
        jan = await service.query(
            user_id=USER,
            arguments=AccountStatementInput(month="2026-01", source="SUBSCRIPTION"),
            now=NOW,
        )
        dec = await service.query(
            user_id=USER,
            arguments=AccountStatementInput(month="2025-12", source="SUBSCRIPTION"),
            now=NOW,
        )
        assert len(jan.transactions) == 1 and dec.transactions == []
        exact = await service.query(
            user_id=USER,
            arguments=AccountStatementInput(
                start_at=when, end_at=when + timedelta(seconds=1), source="SUBSCRIPTION"
            ),
            now=NOW,
        )
        assert exact.transactions == jan.transactions


@pytest.mark.parametrize(
    "arguments",
    [
        {"month": "2026-10", "recent_days": 5},
        {"start_at": "2026-10-01"},
        {"as_of": "2026-10-01"},
        {"limit": 51},
        {"category": "购物"},
        {"user_id": "other"},
    ],
)
def test_invalid_or_forged_statement_arguments_are_rejected(arguments):
    with pytest.raises(ValidationError):
        AccountStatementInput(**arguments)


async def test_public_history_path_persists_bank_evidence_and_replaces_false_model_refusal(
    app, client, monkeypatch
):
    await seed(app)
    monkeypatch.setattr(
        "banking_api.tools.banking.get_account_statement.reference_now", lambda: NOW
    )
    task, events, _, answer = await interact(
        app,
        client,
        [
            call("history", "get_account_statement", {"category": "TRANSFER"}),
            LLMResponse(content="没有任何工具能查询转账记录。"),
        ],
        "我最近有哪些转账",
    )
    assert task.input_json["personal_banking_route"] == "ACCOUNT_QUERY"
    assert task.output_json["statement_results"][0]["total_count"] == 2
    assert "历史收款人" in answer and "123.45" in answer and "已入账" in answer
    assert "没有任何工具" not in answer and "transfer:" not in answer
    assert "analysis_snapshot" not in task.output_json
    assert [e.data_json["tool_name"] for e in events if e.event_type == "tool.call.completed"] == [
        "get_account_statement"
    ]


async def test_combined_history_and_spending_keeps_both_evidence_profiles(app, client, monkeypatch):
    await seed(app)
    monkeypatch.setattr(
        "banking_api.tools.banking.get_account_statement.reference_now", lambda: NOW
    )
    task, _, _, _ = await interact(
        app,
        client,
        [
            route_response("FINANCIAL_ANALYSIS"),
            call("history", "get_account_statement", {"category": "TRANSFER"}),
            call("summary", "get_spending_summary", {"month": "2026-08"}),
            LLMResponse(content="转账流水及8月消费已查询。"),
        ],
        "查转账记录，并分析2026年8月消费",
    )
    assert task.input_json["personal_banking_route"] == "PERSONAL_BANKING"
    assert task.output_json["statement_results"] and task.output_json["analysis_snapshot"]


async def test_next_page_reuses_owned_conversation_query_and_stops_at_end(app, client, monkeypatch):
    await seed(app)
    monkeypatch.setattr(
        "banking_api.tools.banking.get_account_statement.reference_now", lambda: NOW
    )
    task, _, _, _ = await interact(
        app,
        client,
        [
            call("first", "get_account_statement", {"category": "TRANSFER", "limit": 1}),
            LLMResponse(content="首页。"),
        ],
        "我最近有哪些转账",
    )
    first = task.output_json["statement_results"][0]
    from test_routing_integration import build_routed_runner

    runner, provider = build_routed_runner(
        app,
        [
            call(
                "next",
                "get_account_statement",
                {"category": "TRANSFER", "limit": 1, "offset": 1, "as_of": first["as_of"]},
            ),
            LLMResponse(content="下一页。"),
        ],
    )
    app.state.task_runner = runner
    cid = str(task.conversation_id)
    accepted = await client.post(
        f"/api/v1/conversations/{cid}/messages", json={"content": "下一页"}
    )
    tid = UUID(accepted.json()["task_id"])
    await runner.run(tid)
    async with app.state.test_session_factory() as session:
        following = await session.get(TaskModel, tid)
        assert following.status == "COMPLETED", following.error_json
        second = following.output_json["statement_results"][0]
        assert second["offset"] == 1 and second["next_offset"] is None
        assert (
            second["transactions"][0]["transaction_id"]
            != first["transactions"][0]["transaction_id"]
        )
    assert "next_offset" in " ".join(
        m.content or "" for m in provider.requests[0].messages if m.role == "system"
    )
    assert all(request.tools for request in provider.requests)  # No router call.
    done = await client.post(f"/api/v1/conversations/{cid}/messages", json={"content": "下一页"})
    await runner.run(UUID(done.json()["task_id"]))
    messages = (await client.get(f"/api/v1/conversations/{cid}")).json()["messages"]
    assert "没有更多已入账记录" in messages[-1]["content"]
    assert len(provider.requests) == 2


@pytest.mark.parametrize("backend", ["manual", "langgraph"])
@pytest.mark.parametrize(
    "prompt,model_direction,expected",
    [
        ("查询最近30天转给历史收款人的转账记录", None, "DEBIT"),
        ("查看给历史收款人的汇款记录", "CREDIT", "DEBIT"),
        ("查询我收到的转账记录", "DEBIT", "CREDIT"),
        ("查看别人转给我的转账记录", None, "CREDIT"),
    ],
)
async def test_explicit_direction_overrides_missing_or_wrong_model_filter(
    app, monkeypatch, backend, prompt, model_direction, expected
):
    await seed(app)
    monkeypatch.setattr(
        "banking_api.tools.banking.get_account_statement.reference_now", lambda: NOW
    )
    args = {"category": "TRANSFER"}
    if model_direction:
        args["direction"] = model_direction
    runtime, _ = build_runtime(
        backend, [call("direction", "get_account_statement", args), LLMResponse(content="已查询。")]
    )
    runtime.registry.register(
        build_get_account_statement_tool(MockBankService(), app.state.test_session_factory)
    )
    result = await runtime.run(request(prompt))
    fact = result.state.successful_tool_results[0]
    assert fact.arguments["direction"] == expected
    assert fact.output["transactions"]
    assert all(row["direction"] == expected for row in fact.output["transactions"])


@pytest.mark.parametrize("backend", ["manual", "langgraph"])
async def test_pagination_enforces_original_filters_even_when_model_restarts_query(
    app, monkeypatch, backend
):
    await seed(app)
    monkeypatch.setattr(
        "banking_api.tools.banking.get_account_statement.reference_now", lambda: NOW
    )
    filters = AccountStatementInput(category="TRANSFER", limit=1).model_dump(mode="json")
    runtime, _ = build_runtime(
        backend,
        [
            call(
                "page",
                "get_account_statement",
                {"month": "2010", "category": "SHOPPING", "limit": 50},
            ),
            LLMResponse(content="已查询。"),
        ],
    )
    runtime.registry.register(
        build_get_account_statement_tool(MockBankService(), app.state.test_session_factory)
    )
    result = await runtime.run(
        replace(
            request("下一页"),
            statement_context={"filters": filters, "as_of": NOW.isoformat(), "next_offset": 1},
        )
    )
    fact = result.state.successful_tool_results[0]
    assert fact.arguments["category"] == "TRANSFER" and fact.arguments["offset"] == 1
    assert fact.output["total_count"] == 2
    assert len(fact.output["transactions"]) == 1
    assert fact.output["transactions"][0]["direction"] == "DEBIT"


def test_direction_grounding_preserves_separate_queries_and_unknown_keys():
    for prompt in ("查询转入和转出记录", "查询转账记录"):
        assert statement_arguments({"direction": "CREDIT"}, prompt) == {"direction": "CREDIT"}
    scoped = statement_arguments({"user_id": "someone-else"}, "查询转出记录")
    with pytest.raises(ValidationError):
        AccountStatementInput.model_validate(scoped)
