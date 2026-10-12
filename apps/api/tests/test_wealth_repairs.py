"""v0.11.1 regressions run only against isolated databases."""

from datetime import UTC
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_wealth import ACCOUNT, USER, assessment, authorize, commit, draft, recover
from test_wealth import wealth as wealth

from banking_api.config.settings import get_settings
from banking_api.domain.enums import OperationStatus, WorkflowStatus
from banking_api.domain.principal import ExecutionPrincipal
from banking_api.persistence.models import ConversationModel, OperationModel, WorkflowModel
from banking_api.wealth.calculation import WealthError
from banking_api.wealth.intent import extract_quantity
from banking_api.wealth.models import WealthHold, WealthLedger, WealthOrder, WealthPosition
from banking_api.wealth.schemas import RecommendationInput
from banking_api.wealth.service import WealthService
from banking_api.wealth.workflow import WealthWorkflow


def reassemble(wealth, monkeypatch, enabled=False):
    import banking_api.main as main

    factory, clock, balances, _, _, bus = wealth
    monkeypatch.setenv("MOCK_WEALTH_ENABLED", str(enabled).lower())
    get_settings.cache_clear()
    monkeypatch.setattr(main, "session_factory", factory)
    app = main.create_app()
    from banking_api.persistence.database import get_session

    async def sessions():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    app.state.wealth_provider.clock = clock
    return app, (
        factory,
        clock,
        balances,
        app.state.wealth_provider,
        app.state.transfer_workflow_engine,
        bus,
    )


@pytest.mark.parametrize("timeout", [False, True])
async def test_accepted_buy_disable_reassemble_recovers_original(wealth, monkeypatch, timeout):
    factory, clock, balances, provider, _, _ = wealth
    await assessment(wealth)
    provider.fault_mode = "TIMEOUT_AFTER_ACCEPT" if timeout else "SUCCESS"
    initial = await balances.effective_balance(USER, ACCOUNT)
    op = await commit(wealth, await authorize(wealth, await draft(wealth)))
    app, restarted = reassemble(wealth, monkeypatch)
    assert app.state.tool_registry.get("wealth.purchase.status")
    assert app.state.tool_registry.get("wealth.purchase.submit")
    async with factory() as session:
        order = await session.scalar(select(WealthOrder))
        clock.now = order.confirm_at.replace(tzinfo=UTC)
    await recover(restarted)
    await recover(restarted)
    async with factory() as session:
        order = await session.scalar(select(WealthOrder))
        assert order.status == "SETTLED"
        assert (
            await session.get(OperationModel, op.operation_id)
        ).status == OperationStatus.SUCCEEDED
        assert await session.scalar(select(func.count()).select_from(WealthOrder)) == 1
        assert await session.scalar(select(func.count()).select_from(OperationModel)) == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WealthLedger)
                .where(WealthLedger.action == "PURCHASE_DEBIT")
            )
            == 1
        )
        assert not await session.scalar(select(WealthHold.active))
        assert await balances.effective_balance(USER, ACCOUNT) == initial - 1000 + Decimal(
            order.actual["refund"]
        )


async def test_accepted_redeem_disable_restart_confirm_and_credit(wealth, monkeypatch):
    factory, clock, balances, *_ = wealth
    await assessment(wealth)
    buy = await commit(wealth, await authorize(wealth, await draft(wealth)))
    async with factory() as session:
        order = await session.scalar(
            select(WealthOrder).where(WealthOrder.operation_id == buy.operation_id)
        )
        clock.now = order.confirm_at.replace(tzinfo=UTC)
    await recover(wealth)
    sell = await commit(wealth, await authorize(wealth, await draft(wealth, "REDEEM", "10")))
    _, restarted = reassemble(wealth, monkeypatch)
    initial = await balances.effective_balance(USER, ACCOUNT)
    async with factory() as session:
        order = await session.scalar(
            select(WealthOrder).where(WealthOrder.operation_id == sell.operation_id)
        )
        clock.now = order.confirm_at.replace(tzinfo=UTC)
    await recover(restarted)
    async with factory() as session:
        order = await session.scalar(
            select(WealthOrder).where(WealthOrder.operation_id == sell.operation_id)
        )
        result = await WealthService(session, balances, clock).order_result(order)
        assert order.status == "CONFIRMED" and "尚未到账" in result.user_reason
        assert result.last_known_stage == "已成交，待到账"
        assert await balances.effective_balance(USER, ACCOUNT) == initial
        clock.now = order.settle_at.replace(tzinfo=UTC)
    await recover(restarted)
    await recover(restarted)
    async with factory() as session:
        order = await session.scalar(
            select(WealthOrder).where(WealthOrder.operation_id == sell.operation_id)
        )
        assert order.status == "SETTLED"
        assert await balances.effective_balance(USER, ACCOUNT) == initial + Decimal(
            order.actual["net"]
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WealthLedger)
                .where(WealthLedger.action == "REDEEM_CREDIT")
            )
            == 1
        )


async def test_unaccepted_operation_paused_converges_without_holds(wealth, monkeypatch):
    factory, clock, balances, *_ = wealth
    await assessment(wealth)
    w = await authorize(wealth, await draft(wealth))
    async with factory() as session:
        op = await WealthWorkflow(session, balances, clock).prepare(w.workflow_id, USER, w.version)
    _, restarted = reassemble(wealth, monkeypatch)
    await recover(restarted)
    async with factory() as session:
        current = await session.get(OperationModel, op.operation_id)
        assert current.status == OperationStatus.FAILED and current.error_code == "WEALTH_DISABLED"
        assert await session.scalar(select(func.count()).select_from(WealthHold)) == 0
        order = await session.scalar(select(WealthOrder))
        assert order.status == "REJECTED"
        view = await WealthService(session, balances, clock).order_result(order)
        assert "未受理" in view.user_reason and not view.hold_retained
    with pytest.raises(WealthError, match="暂停"):
        await draft(restarted)


async def test_paused_http_reads_owner_scope_writes_and_cancel(wealth, monkeypatch):
    from banking_api.api.dependencies import get_current_principal

    factory, clock, balances, *_ = wealth
    await assessment(wealth)
    w = await draft(wealth)
    app, _ = reassemble(wealth, monkeypatch)
    app.dependency_overrides[get_current_principal] = lambda: ExecutionPrincipal.for_task(USER)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert not (await client.get("/api/v1/wealth/status")).json()["new_business_allowed"]
        for path in (
            "products",
            "positions",
            "orders",
            "questionnaire",
            "risk-assessments/current",
            "workflows",
            "documents/mock-wealth-03:v1:1",
        ):
            assert (await client.get("/api/v1/wealth/" + path)).status_code == 200
        assert (
            await client.post(
                "/api/v1/wealth/risk-assessments",
                json={"questionnaire_version": "mock-v1", "answers": [4] * 8},
            )
        ).status_code == 422
        assert (
            await client.post("/api/v1/wealth/workflows", json={"direction": "PURCHASE"})
        ).status_code == 422
        assert (
            await client.post(
                f"/api/v1/workflows/{w.workflow_id}/actions/approve",
                json={"expected_version": w.version},
            )
        ).status_code == 422
        response = await client.post(
            f"/api/v1/workflows/{w.workflow_id}/actions/cancel",
            json={"expected_version": w.version},
        )
        assert response.status_code == 200
        app.dependency_overrides[get_current_principal] = lambda: ExecutionPrincipal.for_task(
            "another-user"
        )
        assert (await client.get(f"/api/v1/workflows/{w.workflow_id}")).status_code == 404
        assert (await client.get("/api/v1/wealth/positions")).json() == []
        assert (await client.get("/api/v1/wealth/orders")).json() == []
    async with factory() as session:
        assert (await session.get(WorkflowModel, w.workflow_id)).status == WorkflowStatus.CANCELLED


@pytest.mark.parametrize(
    "text,direction,value,unit,all_shares",
    [
        ("申购某产品1000元", "PURCHASE", "1000", "元", False),
        ("申购某产品1000份", "PURCHASE", None, "份", False),
        ("赎回某产品100份", "REDEEM", "100", "份", False),
        ("赎回某产品100元", "REDEEM", None, "元", False),
        ("赎回某产品100", "REDEEM", None, None, False),
        ("赎回某产品全部份额", "REDEEM", None, None, True),
        ("全部赎回", "REDEEM", None, None, True),
        ("申购某产品 ￥ 1,000.00 元", "PURCHASE", "1000.00", "元", False),
        ("申购某产品1000元或2000元", "PURCHASE", None, None, False),
        ("申购某产品1000元1000份", "PURCHASE", None, None, False),
        ("申购某产品1,00元", "PURCHASE", None, "元", False),
        ("申购某产品-1000元", "PURCHASE", None, "元", False),
        ("申购某产品1000.001元", "PURCHASE", None, "元", False),
        ("赎回某产品0.0000001份", "REDEEM", None, "份", False),
        ("申购某产品NaN元", "PURCHASE", None, "元", False),
        ("申购某产品Infinity元", "PURCHASE", None, "元", False),
        ("申购某产品1000000000000元", "PURCHASE", None, "元", False),
    ],
)
def test_quantity_units_ambiguity_and_exact_normalization(text, direction, value, unit, all_shares):
    result = extract_quantity(text, direction)
    assert (result.quantity, result.unit, result.redeem_all) == (value, unit, all_shares)
    if value is None and not all_shares:
        assert result.message


@pytest.mark.parametrize(
    "needs,allowed,first",
    [
        ("必须保本，不能亏本金。", False, None),
        ("只要稳健，不要进取。", True, "R2"),
        ("不要高风险，偏保守。", True, "R1"),
        ("不要求保本，可以承担波动。", True, "R1"),
        ("不需要马上用钱。", True, "R1"),
        ("我想进取，但不能接受任何本金损失。", False, None),
        ("我要即时到账", False, None),
        ("收益一定超过市场", False, None),
    ],
)
async def test_requirements_and_personalized_permissions(wealth, needs, allowed, first):
    factory, clock, balances, *_ = wealth
    await assessment(wealth)
    async with factory() as session:
        result = await WealthService(session, balances, clock).recommend(
            USER, RecommendationInput(needs=needs)
        )
        assert bool(result.products) == allowed
        if allowed:
            assert result.products[0].risk == first
            assert all(
                p.purchase_allowed and p.purchase_block_reason is None for p in result.products
            )
            if "只要稳健" in needs:
                assert all(int(p.risk[1]) <= 2 for p in result.products)
        else:
            assert result.reasons and result.excluded


async def test_all_redeem_free_quantity_snapshot_rechecks_changed_hold(wealth):
    factory, clock, balances, *_ = wealth
    async with factory() as session:
        session.add(
            WealthPosition(
                user_id=USER,
                account_id=ACCOUNT,
                product_id="mock-wealth-03",
                shares=Decimal("10.123456"),
            )
        )
        await session.commit()
    await assessment(wealth)
    w = await draft(wealth, "REDEEM", "1")
    from banking_api.wealth.schemas import WealthEditInput

    async with factory() as session:
        wf = WealthWorkflow(session, balances, clock)
        w = await wf.edit(
            w.workflow_id, USER, WealthEditInput(expected_version=w.version, redeem_all=True)
        )
        assert w.state_json["draft"]["quantity"] == "10.123456"
        assert w.state_json["review"]["quantity_display"] == "10.123456 份"
    w = await authorize(wealth, w)
    await commit(wealth, await authorize(wealth, await draft(wealth, "REDEEM", "1")))
    with pytest.raises(WealthError, match="份额不足"):
        await commit(wealth, w)
    async with factory() as session:
        frozen = await WealthService(session, balances, clock).frozen(
            USER, ACCOUNT, "mock-wealth-03"
        )
        assert frozen == 1
        assert await session.scalar(select(func.count()).select_from(OperationModel)) == 1


async def test_page_creation_is_atomic_and_idempotent(wealth, monkeypatch):
    from banking_api.api.dependencies import get_current_principal

    factory, *_ = wealth
    await assessment(wealth)
    app, _ = reassemble(wealth, monkeypatch, True)
    app.dependency_overrides[get_current_principal] = lambda: ExecutionPrincipal.for_task(USER)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        key = str(uuid4())
        invalid = await client.post(
            "/api/v1/wealth/workflows",
            json={
                "direction": "REDEEM",
                "product_id": "mock-wealth-03",
                "account_id": ACCOUNT,
                "redeem_all": True,
                "creation_key": key,
            },
        )
        assert invalid.status_code == 422
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(ConversationModel)) == 0
        payload = {
            "direction": "PURCHASE",
            "product_id": "mock-wealth-03",
            "account_id": ACCOUNT,
            "creation_key": key,
        }
        a = await client.post("/api/v1/wealth/workflows", json=payload)
        b = await client.post("/api/v1/wealth/workflows", json=payload)
        assert a.status_code == b.status_code == 200
        assert a.json()["workflow_id"] == b.json()["workflow_id"]
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(ConversationModel)) == 1
            assert await session.scalar(select(func.count()).select_from(WorkflowModel)) == 1


async def test_http_and_agent_recommendations_identical_owner_flags(wealth, monkeypatch):
    from banking_api.api.dependencies import get_current_principal

    await assessment(wealth)
    app, _ = reassemble(wealth, monkeypatch, True)
    app.dependency_overrides[get_current_principal] = lambda: ExecutionPrincipal.for_task(USER)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for needs in (
            "必须保本，不能亏本金",
            "只要稳健，不要进取",
            "不要高风险，偏保守",
            "不要求保本，可以承担波动",
            "不需要马上用钱",
            "我想进取，但不能接受任何本金损失",
        ):
            body = {"needs": needs}
            response = await client.post("/api/v1/wealth/recommendations", json=body)
            assert response.status_code == 200
            output = await app.state.transfer_workflow_engine._executor.execute(
                tool_name="wealth_recommend",
                arguments=body,
                caller="agent:wealth-advisor",
                principal=ExecutionPrincipal.for_task(USER),
                agent_allowlist=frozenset({"wealth.recommend"}),
            )
            assert output.ok
            assert response.json() == {key: output.output[key] for key in response.json()}


async def test_unknown_and_missing_nav_typed_explanations(wealth):
    from sqlalchemy import delete

    from banking_api.wealth.models import WealthNav

    factory, clock, balances, provider, *_ = wealth
    await assessment(wealth)
    provider.fault_mode = "TIMEOUT_AFTER_ACCEPT"
    op = await commit(wealth, await authorize(wealth, await draft(wealth)))
    async with factory() as session:
        order = await session.scalar(select(WealthOrder))
        result = await WealthService(session, balances, clock).order_result(order)
        assert result.unknown and result.hold_retained
        assert "无需重新下单" in result.next_step
        await session.execute(
            delete(WealthNav).where(
                WealthNav.product_id == order.product_id, WealthNav.nav_date == order.trade_date
            )
        )
        clock.now = order.confirm_at.replace(tzinfo=UTC)
        await session.commit()
    await recover(wealth)
    async with factory() as session:
        order = await session.scalar(select(WealthOrder))
        result = await WealthService(session, balances, clock).order_result(order)
        assert result.error_code == "NAV_MISSING" and result.hold_retained
        assert "缺少成交日" in result.user_reason
        assert result.next_processing_at is not None
        assert (
            await session.get(OperationModel, op.operation_id)
        ).status != OperationStatus.SUCCEEDED


@pytest.mark.parametrize(
    "text",
    [
        "从工资卡赎回演示稳健优选100元",
        "从工资卡赎回演示稳健优选100",
        "从工资卡赎回演示稳健优选10份或20份",
        "从工资卡申购演示稳健优选1000份",
    ],
)
async def test_natural_bad_units_never_produce_complete_review(wealth, text):
    from banking_api.application.conversation_service import ConversationService
    from banking_api.domain.enums import RuntimeBackend
    from banking_api.llm.fake_provider import FakeLLMProvider
    from banking_api.routing.request_router import RequestRouter
    from banking_api.runtime.runtime_factory import AgentRuntimeFactory
    from banking_api.runtime.task_runner import InProcessTaskRunner

    await assessment(wealth)  # Purchase drafts require valid assessment before unit completion.
    factory, _, _, _, engine, bus = wealth
    async with factory() as session:
        service = ConversationService(session, bus, runtime_backend=RuntimeBackend.LANGGRAPH)
        c = await service.create(user_id=USER, title="单位测试")
        accepted = await service.accept_message(
            conversation_id=c.conversation_id, user_id=USER, content=text
        )
    from banking_api.agents.wealth_advisor_agent import WEALTH_ADVISOR_AGENT
    from banking_api.registries.agent_registry import AgentRegistry

    agents = AgentRegistry()
    agents.register(WEALTH_ADVISOR_AGENT)
    runner = InProcessTaskRunner(
        factory,
        bus,
        AgentRuntimeFactory(),
        default_backend=RuntimeBackend.LANGGRAPH,
        router=RequestRouter(FakeLLMProvider([])),
        agent_registry=agents,
        transfer_workflow_engine=engine,
    )
    await runner.run(accepted.task_id)
    async with factory() as session:
        wf = await session.scalar(
            select(WorkflowModel).where(WorkflowModel.source_task_id == accepted.task_id)
        )
        if wf:
            assert wf.state_json["draft"]["quantity"] is None
            assert wf.state_json["review"] is None and wf.state_json["validation_message"]
        else:
            from banking_api.persistence.models import TaskModel

            task = await session.get(TaskModel, accepted.task_id)
            assert task.output_json["wealth_analysis"]["status"] == "NEEDS_CLARIFICATION"
            assert task.output_json["wealth_analysis"]["needs"]["amount"] is None
        assert await session.scalar(select(func.count()).select_from(OperationModel)) == 0


async def test_unknown_unaccepted_paused_converges_without_phantom_order(wealth, monkeypatch):
    factory, clock, balances, *_ = wealth
    await assessment(wealth)
    w = await authorize(wealth, await draft(wealth))
    async with factory() as session:
        op = await WealthWorkflow(session, balances, clock).prepare(w.workflow_id, USER, w.version)
        op.status = OperationStatus.UNKNOWN
        await session.commit()
    _, restarted = reassemble(wealth, monkeypatch)
    await recover(restarted)
    async with factory() as session:
        op = await session.get(OperationModel, op.operation_id)
        assert op.status == OperationStatus.FAILED and op.error_code == "WEALTH_DISABLED"
        assert await session.scalar(select(func.count()).select_from(WealthHold)) == 0
        assert await session.scalar(select(func.count()).select_from(WealthOrder)) == 0
        wf = await session.get(WorkflowModel, w.workflow_id)
        assert "未受理" in wf.state_json["validation_message"]


async def test_failure_details_timezone_and_owner_order_reads(wealth, monkeypatch):
    from banking_api.api.dependencies import get_current_principal

    factory, clock, balances, provider, *_ = wealth
    await assessment(wealth)
    provider.fault_mode = "REJECT_BEFORE_ACCEPT"
    op = await commit(wealth, await authorize(wealth, await draft(wealth)))
    app, _ = reassemble(wealth, monkeypatch)
    app.dependency_overrides[get_current_principal] = lambda: ExecutionPrincipal.for_task(USER)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        orders = (await client.get("/api/v1/wealth/orders")).json()
        assert len(orders) == 1
        order = orders[0]
        assert order["error_code"] == "PROVIDER_REJECTED"
        assert "明确拒绝" in order["user_reason"] and "无资金或份额占用" in order["user_reason"]
        assert order["next_step"] and order["source_task_id"] and order["conversation_id"]
        assert order["confirm_at"].endswith("Z") or order["confirm_at"].endswith("+00:00")
        assert order["next_processing_at"] is None
        app.dependency_overrides[get_current_principal] = lambda: ExecutionPrincipal.for_task(
            "another-user"
        )
        assert (await client.get(f"/api/v1/wealth/orders/{order['order_id']}")).status_code == 404
        assert (await client.get(f"/api/v1/operations/{op.operation_id}")).status_code == 404


async def test_all_redeem_zero_and_ambiguous_position_need_selection(wealth):
    factory, clock, balances, *_ = wealth
    async with factory() as session:
        wf = WealthWorkflow(session, balances, clock)
        with pytest.raises(WealthError, match="没有对应持仓"):
            await wf.resolve_draft(USER, {"direction": "REDEEM", "redeem_all": True})
        session.add(
            WealthPosition(
                user_id=USER, account_id=ACCOUNT, product_id="mock-wealth-03", shares=Decimal(0)
            )
        )
        await session.commit()
        with pytest.raises(WealthError, match="没有可赎回份额"):
            await wf.resolve_draft(
                USER,
                {
                    "direction": "REDEEM",
                    "product_id": "mock-wealth-03",
                    "account_id": ACCOUNT,
                    "redeem_all": True,
                },
            )
        session.add(
            WealthPosition(
                user_id=USER,
                account_id="acc_savings",
                product_id="mock-wealth-03",
                shares=Decimal(1),
            )
        )
        await session.commit()
        d = await wf.resolve_draft(
            USER, {"direction": "REDEEM", "product_id": "mock-wealth-03", "redeem_all": True}
        )
        assert d.get("quantity") is None and "唯一确定" in d["quantity_message"]


async def test_late_balance_rejection_has_specific_reason_and_no_own_hold(wealth):
    factory, clock, balances, provider, *_ = wealth
    await assessment(wealth)
    w = await authorize(wealth, await draft(wealth))
    async with factory() as session:
        op = await WealthWorkflow(session, balances, clock).prepare(w.workflow_id, USER, w.version)
    initial = await balances.effective_balance(USER, ACCOUNT)
    await commit(
        wealth,
        await authorize(wealth, await draft(wealth, value=str(initial), pid="mock-wealth-01")),
    )
    result = await provider.submit(op.operation_id, USER, "PURCHASE")
    assert result["outcome"] == "FAILED" and result["error_code"] == "INSUFFICIENT_FUNDS"
    async with factory() as session:
        order = await session.scalar(
            select(WealthOrder).where(WealthOrder.operation_id == op.operation_id)
        )
        view = await WealthService(session, balances, clock).order_result(order)
        assert "账户可用余额不足" in view.user_reason and not view.hold_retained
        assert "核对账户" in view.next_step
        assert not await session.scalar(
            select(WealthHold).where(WealthHold.order_id == order.order_id)
        )
