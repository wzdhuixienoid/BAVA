from decimal import Decimal
from uuid import UUID

import pytest
from banking_test_helpers import authenticate_workflow
from test_transfer_operations import operation_runtime

from banking_api.application.aa_service import AAIntent, AAService, AAUpdate, split_cents
from banking_api.application.conversation_service import ConversationService
from banking_api.application.operation_service import OperationActionError, OperationService
from banking_api.application.workflow_service import WorkflowService
from banking_api.mock_bank.service import MockBankService
from banking_api.transfers.provider import TransferProviderFaultMode


def test_split_remainders_manual_and_zero():
    assert split_cents(Decimal("100"), ["张三", "李四", "我"], None) == [3334, 3333, 3333]
    assert split_cents(
        Decimal("100"), ["张三", "李四"], {"张三": Decimal("60"), "李四": Decimal("40")}
    ) == [6000, 4000]
    for total, names, manual in [
        ("1", ["a", "a"], None),
        ("0.01", ["a", "b"], None),
        ("1.001", ["a"], None),
        ("1", ["a"], {"a": Decimal("0")}),
        ("100", ["a", "b"], {"a": Decimal("30"), "b": Decimal("40")}),
    ]:
        with pytest.raises(OperationActionError):
            split_cents(Decimal(total), names, manual)


async def aa_runtime(app, fault=TransferProviderFaultMode.SUCCESS):
    bank, provider, registry, engine = operation_runtime(app, fault_mode=fault)
    extra = MockBankService(
        fixture_user_ids=frozenset({"mock-zhangsan", "mock-lisi", "mock-wangwu"})
    )
    bank._accounts.extend(extra._accounts)

    async def resolve(**kwargs):
        async with app.state.test_session_factory() as session:
            return await AAService(session, app.state.event_bus, engine, bank).resolve_payment(
                **kwargs
            )

    engine.aa_resolver = resolve
    app.state.mock_bank = bank
    return bank, provider, engine


async def published_request(app, bank, engine):
    async with app.state.test_session_factory() as session:
        conv = await ConversationService(session, app.state.event_bus).create(
            user_id="dev-user-001", title="聚餐 AA"
        )
        accepted = await ConversationService(session, app.state.event_bus).accept_message(
            conversation_id=conv.conversation_id,
            user_id="dev-user-001",
            content="100元和张三李四AA我参与",
        )
        intent = AAIntent(
            total="100", participants=["张三", "李四"], initiator_participates=True, remark="聚餐"
        )
        service = AAService(session, app.state.event_bus, engine, bank)
        draft = await service.create(
            user_id="dev-user-001",
            conversation_id=conv.conversation_id,
            source_task_id=accepted.task_id,
            intent=intent,
        )
        assert "required_input" in draft
        changed = await service.update(
            UUID(draft["request_id"]),
            "dev-user-001",
            AAUpdate(
                expected_version=draft["version"],
                intent=intent,
                collection_account_id="acc_savings",
            ),
        )
        assert [p["amount"] for p in changed["preview"]["participants"]] == [
            "33.34",
            "33.33",
            "33.33",
        ]
        result = await service.publish(
            UUID(draft["request_id"]), "dev-user-001", changed["version"]
        )
        assert result["self_paid"] == "33.33" and result["received"] == "0.00"
        return result


async def pay(app, bank, engine, request, participant, share_id):
    async with app.state.test_session_factory() as session:
        workflow = await AAService(session, app.state.event_bus, engine, bank).payment(
            UUID(share_id), participant, request["version"], "acc_salary"
        )
        approved = await WorkflowService(session, app.state.event_bus, engine).approve(
            workflow.workflow_id, user_id=participant, expected_version=workflow.version
        )
    ready = await authenticate_workflow(app, engine, approved)
    async with app.state.test_session_factory() as session:
        operation = await OperationService(session, app.state.event_bus, engine).commit_workflow(
            ready.workflow_id, user_id=participant, expected_version=ready.version
        )
    return operation


async def test_aa_independent_payments_credit_once_and_isolation(app):
    bank, provider, engine = await aa_runtime(app)
    request = await published_request(app, bank, engine)
    before = await provider.effective_balance("dev-user-001", "acc_savings")
    shares = request["shares"]
    async with app.state.test_session_factory() as session:
        service = AAService(session, app.state.event_bus, engine, bank)
        with pytest.raises(OperationActionError, match="NOT_FOUND"):
            await service.get(UUID(request["request_id"]), "outsider")
        with pytest.raises(OperationActionError, match="NOT_FOUND"):
            await service.payment(
                UUID(shares[0]["share_id"]), "dev-user-001", request["version"], "acc_salary"
            )
    first = await pay(app, bank, engine, request, "mock-zhangsan", shares[0]["share_id"])
    async with app.state.test_session_factory() as session:
        result = await AAService(session, app.state.event_bus, engine, bank).get(
            UUID(request["request_id"]), "dev-user-001"
        )
        assert result["status"] == "PARTIAL" and result["received"] == "33.34"
        assert result["shares"][1]["status"] == "PENDING"
        assert all(s["workflow_id"] is None for s in result["shares"])
        with pytest.raises(OperationActionError, match="SUBMITTED_OR_CLOSED"):
            await AAService(session, app.state.event_bus, engine, bank).close_share(
                UUID(shares[0]["share_id"]), "dev-user-001", request["version"]
            )
    assert await provider.effective_balance("dev-user-001", "acc_savings") == before + Decimal(
        "33.34"
    )
    async with app.state.test_session_factory() as session:
        repeated = await AAService(session, app.state.event_bus, engine, bank).payment(
            UUID(shares[0]["share_id"]), "mock-zhangsan", request["version"], "acc_salary"
        )
        replay = await OperationService(session, app.state.event_bus, engine).commit_workflow(
            repeated.workflow_id, user_id="mock-zhangsan", expected_version=repeated.version
        )
        assert replay.operation_id == first.operation_id
    await pay(app, bank, engine, request, "mock-lisi", shares[1]["share_id"])
    async with app.state.test_session_factory() as session:
        result = await AAService(session, app.state.event_bus, engine, bank).get(
            UUID(request["request_id"]), "dev-user-001"
        )
        assert result["status"] == "COLLECTED" and result["received"] == "66.67"
    assert await provider.effective_balance("dev-user-001", "acc_savings") == before + Decimal(
        "66.67"
    )
    assert await provider.transfer_count() == 2


@pytest.mark.parametrize(
    "fault",
    [TransferProviderFaultMode.DEFINITIVE_FAILURE, TransferProviderFaultMode.TIMEOUT_AFTER_ACCEPT],
)
async def test_aa_failure_unknown_no_premature_credit(app, fault):
    bank, provider, engine = await aa_runtime(app, fault)
    request = await published_request(app, bank, engine)
    before = await provider.effective_balance("dev-user-001", "acc_savings")
    operation = await pay(
        app, bank, engine, request, "mock-zhangsan", request["shares"][0]["share_id"]
    )
    assert operation.status.value == (
        "FAILED" if fault == TransferProviderFaultMode.DEFINITIVE_FAILURE else "UNKNOWN"
    )
    assert await provider.effective_balance("dev-user-001", "acc_savings") == before
    async with app.state.test_session_factory() as session:
        assert (
            await AAService(session, app.state.event_bus, engine, bank).get(
                UUID(request["request_id"]), "dev-user-001"
            )
        )["received"] == "0.00"
        if fault == TransferProviderFaultMode.TIMEOUT_AFTER_ACCEPT:
            reconciled = await OperationService(session, app.state.event_bus, engine).reconcile(
                operation.operation_id, user_id="mock-zhangsan", expected_version=operation.version
            )
            assert reconciled.status.value == "SUCCEEDED"
    if fault == TransferProviderFaultMode.TIMEOUT_AFTER_ACCEPT:
        assert await provider.effective_balance("dev-user-001", "acc_savings") == before + Decimal(
            "33.34"
        )
        assert await provider.transfer_count() == 1


async def test_aa_taskrunner_extracts_only_semantics_and_does_not_debit(app):
    from test_transfer_workflow import build_transfer_runtime, create_transfer_task

    from banking_api.application.aa_intent_extractor import AAIntentExtractor
    from banking_api.llm.models import LLMResponse
    from banking_api.persistence.models import TaskModel

    runner, bank, _, provider = build_transfer_runtime(
        app,
        [
            LLMResponse(
                content='{"route":"AA_COLLECTION","requested_output":"WORKFLOW","confidence":1}'
            ),
            LLMResponse(
                content='{"total":"268","participants":["张三","李四","王五"],"initiator_participates":true,"remark":"聚餐"}'
            ),
        ],
    )
    runner.aa_bank, runner.aa_intent_extractor = bank, AAIntentExtractor(provider)
    _, accepted = await create_transfer_task(app, runner)
    async with app.state.test_session_factory() as session:
        task = await session.get(TaskModel, accepted.task_id)
        assert task.status.value == "COMPLETED" and task.output_json["aa_request_id"]
        request = await AAService(
            session, app.state.event_bus, runner.transfer_workflow_engine, bank
        ).get(UUID(task.output_json["aa_request_id"]), "dev-user-001")
        assert request["status"] == "DRAFT" and request["snapshot"] is None
