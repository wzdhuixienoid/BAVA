from datetime import UTC, datetime
from decimal import Decimal

from banking_api.agents.financial_analysis_agent import FINANCIAL_ANALYSIS_AGENT_ID
from banking_api.domain.enums import RequestedOutput
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.financial.models import CategorySpending, TopTransaction
from banking_api.mock_bank.service import MockBankService
from banking_api.runtime.base import SuccessfulToolResult
from banking_api.runtime.task_runner import InProcessTaskRunner


def test_display_fields_preserve_raw_facts_and_format_percentage():
    category = CategorySpending(
        category="HOUSING",
        amount=Decimal("6200.00"),
        transaction_count=1,
        share=Decimal("0.6718136258973317079777868075"),
    )
    output = category.model_dump(mode="json")
    assert output["category_display"] == "住房"
    assert output["share_display"] == "67.18%"
    assert output["share"] == "0.6718136258973317079777868075"
    for value, expected in [("0", "0.00%"), ("1", "100.00%"), ("0.99995", "100.00%")]:
        assert category.model_copy(update={"share": Decimal(value)}).share_display == expected


def test_transaction_display_fields():
    item = TopTransaction(
        transaction_id="tx",
        occurred_at=datetime(2026, 9, 3, 12, 20, tzinfo=UTC),
        merchant="公寓",
        description="月租",
        category="HOUSING",
        amount=Decimal("6200"),
        currency="CNY",
        account_id="acc_salary",
        account_display="工资卡",
    )
    assert item.category_display == "住房"
    assert item.account_display == "工资卡"
    assert item.occurred_at_display == "2026年09月03日 20:20"


def test_plain_analysis_does_not_attach_report_display():
    analytics = FinancialAnalyticsService(MockBankService())
    facts = [
        SuccessfulToolResult(
            capability_id="transaction.spending_summary",
            tool_name="get_spending_summary",
            arguments={"month": "2026-09"},
            output=analytics.spending_summary("2026-09", user_id="dev-user-001").model_dump(
                mode="json"
            ),
        ),
        SuccessfulToolResult(
            capability_id="transaction.category_breakdown",
            tool_name="get_category_breakdown",
            arguments={"month": "2026-09"},
            output=analytics.category_breakdown("2026-09", user_id="dev-user-001").model_dump(
                mode="json"
            ),
        ),
    ]
    output = InProcessTaskRunner._build_task_output(
        agent_id=FINANCIAL_ANALYSIS_AGENT_ID,
        assistant_message_id="message",
        steps=1,
        tool_calls=2,
        successful_tool_results=facts,
        requested_output=RequestedOutput.ANSWER,
    )
    assert "analysis_snapshot" in output
    assert "financial_display" not in output


def test_saved_account_names_are_scoped_and_do_not_mutate_facts():
    from types import SimpleNamespace

    from banking_api.financial.presentation import with_account_names

    output = {
        "analysis_snapshot": {
            "top_transactions": {
                "transactions": [
                    {"account_id": "acc_salary"},
                    {"account_id": "unknown"},
                ]
            }
        }
    }

    class SavedTask(SimpleNamespace):
        def model_copy(self, *, update):
            return SavedTask(**{**vars(self), **update})

    task = SavedTask(output=output)
    rendered = with_account_names(
        task,
        [
            {"account_id": "acc_salary", "display_name": "工资卡"},
            {"account_id": "unreferenced", "display_name": "储蓄卡"},
        ],
    )
    assert rendered.output["financial_account_names"] == {"acc_salary": "工资卡"}
    assert "financial_account_names" not in task.output
    assert with_account_names(task, []).output["financial_account_names"] == {}
