"""Statement analysis covers every filtered posting, not the visible page."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from test_personal_banking_integration import interact
from test_routing_integration import call
from test_statement_tool import seed as seed_legacy

from banking_api.application.account_statement_service import AccountStatementService
from banking_api.domain.statement import AccountStatementInput, AccountStatementResult
from banking_api.llm.models import LLMResponse
from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import MockBankTransferModel, PayeeModel, TaskModel

NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)
USER = "dev-user-001"


async def seed_transfers(app):
    bank = MockBankService()
    bank._transactions = []
    async with app.state.test_session_factory() as session:
        session.add(
            PayeeModel(
                payee_id="recipient-wang",
                user_id=USER,
                display_name="王五",
                bank_name="森林银行（虚构）",
                account_suffix="8888",
            )
        )
        for index, (payee, amount) in enumerate(
            [
                ("payee_001", "10"),
                ("payee_001", "10"),
                ("payee_001", "10"),
                ("payee_002", "20"),
                ("recipient-wang", "30"),
                (None, "40"),
            ]
        ):
            when = NOW - timedelta(hours=index + 1)
            session.add(
                MockBankTransferModel(
                    provider_reference=f"analysis-{index}",
                    idempotency_key=uuid4(),
                    user_id=USER if payee else "synthetic-sender",
                    source_account_id="acc_salary",
                    payee_id=payee or "payee_001",
                    amount=Decimal(amount),
                    currency="CNY",
                    status="SUCCEEDED",
                    applied_at=when,
                    created_at=when,
                    destination_user_id=USER if payee is None else None,
                    destination_account_id="acc_savings" if payee is None else None,
                    credited_at=when if payee is None else None,
                )
            )
        await session.commit()
    return bank


async def test_transfer_totals_recipient_identity_and_latest_are_independent_of_page(app):
    bank = await seed_transfers(app)
    async with app.state.test_session_factory() as session:
        service = AccountStatementService(bank, session)
        first = await service.query(
            user_id=USER, arguments=AccountStatementInput(category="TRANSFER", limit=1), now=NOW
        )
        second = await service.query(
            user_id=USER,
            arguments=AccountStatementInput(
                category="TRANSFER", limit=1, offset=1, as_of=first.as_of
            ),
            now=NOW,
        )
    assert first.total_count == 6 and len(first.transactions) == 1
    assert first.summary == second.summary
    total = first.summary.totals[0]
    assert (total.total_debit, total.debit_count) == (Decimal("80"), 5)
    assert (total.total_credit, total.credit_count) == (Decimal("40"), 1)
    zhang = [g for g in first.summary.counterparties if g.display_name.startswith("张三")]
    assert len(zhang) == 2
    assert {(g.amount, g.transaction_count) for g in zhang} == {
        (Decimal("30"), 3),
        (Decimal("20"), 1),
    }
    assert any("2231" in g.display_name and g.share_display == "37.5%" for g in zhang)
    assert any("9102" in g.display_name and g.share_display == "25.0%" for g in zhang)
    assert first.summary.latest_transaction.transaction_id == first.transactions[0].transaction_id
    assert first.summary.latest_transaction.transaction_id != second.transactions[0].transaction_id
    assert "转账总览" in first.answer and "按收款人／付款方汇总" in first.answer
    assert "¥80.00 / 5笔" in first.answer and "¥40.00 / 1笔" in first.answer
    assert "最近一笔" in first.answer and "最近转账明细" in first.answer
    assert "并列最高" in first.summary.insights[0]
    assert first.summary.grouping_note is not None  # Incoming bank data has no payer identity.
    # The saved tool DTO remains valid after serialization and transcript reload.
    assert AccountStatementResult.model_validate(first.model_dump(mode="json")) == first


async def test_recipient_and_direction_filters_apply_before_aggregation(app):
    bank = await seed_transfers(app)
    async with app.state.test_session_factory() as session:
        page = await AccountStatementService(bank, session).query(
            user_id=USER,
            arguments=AccountStatementInput(
                category="TRANSFER",
                query="张三",
                direction="DEBIT",
                account_ids=["acc_salary"],
                limit=1,
            ),
            now=NOW,
        )
    assert page.total_count == 4
    assert page.summary.totals[0].total_debit == Decimal("50")
    assert page.summary.totals[0].credit_count == 0
    assert len(page.summary.counterparties) == 2
    assert "工资卡" in page.summary.scope_display and "张三" in page.summary.scope_display
    assert "王五" not in page.answer


def transaction(identity, amount, currency="CNY", direction="DEBIT"):
    return dict(
        transaction_id=identity,
        user_id=USER,
        account_id="acc_salary" if currency == "CNY" else "acc_savings",
        occurred_at=(NOW - timedelta(hours=1)).isoformat(),
        merchant="测试商户",
        description="合成记录",
        amount=amount,
        currency=currency,
        direction=direction,
        category="SHOPPING",
        status="POSTED",
    )


async def test_decimal_totals_keep_currencies_and_directions_separate(app):
    bank = MockBankService()
    for account in bank._accounts:
        if account["account_id"] == "acc_savings":
            account["currency"] = "USD"
    bank._transactions = [
        transaction("a", "0.10"),
        transaction("b", "0.20"),
        transaction("c", "0.30", "USD"),
        transaction("d", "0.70", "USD", "CREDIT"),
    ]
    async with app.state.test_session_factory() as session:
        page = await AccountStatementService(bank, session).query(
            user_id=USER, arguments=AccountStatementInput(limit=1), now=NOW
        )
    totals = {t.currency: t for t in page.summary.totals}
    assert totals["CNY"].total_debit == Decimal("0.30")
    assert totals["CNY"].debit_display == "¥0.30"
    assert totals["USD"].total_debit == Decimal("0.30")
    assert totals["USD"].total_credit == Decimal("0.70")
    assert "美元" in page.answer and "人民币" in page.answer
    assert "$0.30" in page.answer and "$0.70" in page.answer
    assert "转账总览" not in page.answer


async def test_bounded_group_display_keeps_all_postings_in_totals(app):
    bank = MockBankService()
    bank._transactions = [
        transaction(str(index), "1") | {"merchant": f"商户{index}"} for index in range(25)
    ]
    async with app.state.test_session_factory() as session:
        page = await AccountStatementService(bank, session).query(
            user_id=USER, arguments=AccountStatementInput(limit=1), now=NOW
        )
    assert page.summary.counterparty_group_count == 25
    assert len(page.summary.counterparties) == 20
    assert page.summary.totals[0].total_debit == Decimal("25")
    assert "其余记录仍包含在总额中" in page.answer


async def test_bank_text_cannot_add_markdown_links_or_columns(app):
    bank = MockBankService()
    bank._transactions = [
        transaction("markdown", "10") | {"merchant": "[点我](https://example.test)|额外列\n# 标题"}
    ]
    async with app.state.test_session_factory() as session:
        page = await AccountStatementService(bank, session).query(
            user_id=USER, arguments=AccountStatementInput(), now=NOW
        )
    assert "\\[点我\\]" in page.answer and "\\|额外列" in page.answer
    assert "\n# 标题" not in page.answer


async def test_empty_analysis_has_no_invented_totals_or_latest(app):
    bank = MockBankService()
    bank._transactions = []
    async with app.state.test_session_factory() as session:
        page = await AccountStatementService(bank, session).query(
            user_id=USER, arguments=AccountStatementInput(category="TRANSFER"), now=NOW
        )
    assert page.summary.totals == [] and page.summary.latest_transaction is None
    assert "没有已入账记录" in page.answer and "转账总览" not in page.answer


@pytest.mark.parametrize("limit,complete", [(10, True), (1, False)])
async def test_historical_presentation_only_summarizes_complete_saved_facts(
    app, client, monkeypatch, limit, complete
):
    await seed_legacy(app)
    monkeypatch.setattr(
        "banking_api.tools.banking.get_account_statement.reference_now", lambda: NOW
    )
    task, _, _, _ = await interact(
        app,
        client,
        [
            call("history", "get_account_statement", {"category": "TRANSFER", "limit": limit}),
            LLMResponse(content="原回复。"),
        ],
        "我最近有哪些转账",
    )
    async with app.state.test_session_factory() as session:
        saved = await session.get(TaskModel, task.task_id)
        output = dict(saved.output_json)
        page = dict(output["statement_results"][0])
        page.pop("summary")
        page.pop("answer")
        for row in page["transactions"]:
            for name in ("counterparty_id", "counterparty_bank", "counterparty_account"):
                row.pop(name, None)
        saved.output_json = output | {"statement_results": [page]}
        await session.commit()
    response = await client.get(f"/api/v1/tasks/{task.task_id}")
    assert response.status_code == 200
    page = response.json()["output"]["statement_results"][0]
    if complete:
        assert page["summary"]["totals"][0]["debit_display"] == "¥123.45"
        assert "转账总览" in page["answer"] and "历史查询快照" in page["answer"]
    else:
        assert page["summary"] is None and page["answer"] is None
    async with app.state.test_session_factory() as session:
        saved = await session.get(TaskModel, task.task_id)
        assert "summary" not in saved.output_json["statement_results"][0]
        assert "answer" not in saved.output_json["statement_results"][0]
