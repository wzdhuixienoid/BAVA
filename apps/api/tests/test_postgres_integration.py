import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from banking_api.agents.minimal_banking_agent import MINIMAL_BANKING_AGENT
from banking_api.application.conversation_service import ConversationService
from banking_api.application.operation_recovery_policy import OperationRecoveryPolicy
from banking_api.application.operation_service import (
    OperationActionError,
    OperationLeaseLostError,
    OperationNotFoundError,
    OperationService,
)
from banking_api.application.outbox_publication_policy import OutboxPublicationPolicy
from banking_api.application.report_service import ReportService
from banking_api.application.task_execution_policy import TaskExecutionPolicy
from banking_api.application.task_service import TaskService
from banking_api.application.workflow_service import (
    WorkflowNotFoundError,
    WorkflowService,
    WorkflowVersionConflictError,
)
from banking_api.context.builder import ContextBuilder
from banking_api.domain.enums import (
    ApprovalStatus,
    MessageRole,
    OperationStatus,
    ReauthenticationStatus,
    RuntimeBackend,
    TaskStatus,
    WorkflowStatus,
)
from banking_api.domain.message import Message
from banking_api.domain.principal import ExecutionPrincipal
from banking_api.financial.analysis_snapshot import FinancialAnalysisSnapshot, ToolEvidence
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.llm.models import LLMResponse, LLMToolCall
from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import (
    ApprovalModel,
    ConversationModel,
    EventModel,
    MockBankTransferModel,
    OperationModel,
    OutboxEventModel,
    ReauthenticationModel,
    SecurityGuardStateModel,
    TaskModel,
    WorkflowModel,
)
from banking_api.persistence.repositories.conversations import ConversationRepository
from banking_api.persistence.repositories.operations import OperationRepository
from banking_api.persistence.repositories.outbox import OutboxRepository
from banking_api.persistence.repositories.tasks import TaskRepository
from banking_api.policy.service import PolicyService
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.runtime.agent_runtime import AgentRuntime
from banking_api.runtime.base import AgentRunRequest
from banking_api.runtime.event_bus import EventBus
from banking_api.runtime.event_publisher import EventPublisher
from banking_api.runtime.langgraph.checkpoint import (
    LangGraphCheckpointManager,
    normalize_checkpoint_database_url,
)
from banking_api.runtime.langgraph.graph import LangGraphAgentRuntime
from banking_api.runtime.operation_recovery_worker import OperationRecoveryWorker
from banking_api.runtime.outbox_publisher import OutboxPublisher
from banking_api.runtime.runtime_factory import AgentRuntimeFactory
from banking_api.runtime.task_execution_worker import (
    TaskExecutionWorker,
    TaskLeaseLostError,
)
from banking_api.runtime.task_reconciliation import TaskReconciliationService
from banking_api.runtime.task_runner import InProcessTaskRunner
from banking_api.security.guard import (
    SecurityGuardService,
    SecurityGuardStatus,
    SecurityWriteLockedError,
    acquire_security_user_lock,
)
from banking_api.security.reauthentication.mock_provider import MockReauthenticationProvider
from banking_api.skill_runtime.executor import SkillExecutor
from banking_api.skills.monthly_spending_report import MonthlySpendingReportSkill
from banking_api.subscriptions.provider import MockSubscriptionProvider
from banking_api.tools.banking import (
    build_commit_transfer_tool,
    build_get_balance_tool,
    build_get_transfer_status_tool,
    build_list_accounts_tool,
    build_search_payees_tool,
)
from banking_api.tools.executor import ToolExecutor
from banking_api.tools.subscriptions import (
    build_subscription_analyze_tool,
    build_subscription_cancel_tool,
    build_subscription_status_tool,
)
from banking_api.transfers.mock_provider import MockTransferProvider
from banking_api.transfers.provider import TransferProviderRequest
from banking_api.workflows.subscription_cancel.engine import SubscriptionCancellationWorkflow
from banking_api.workflows.subscription_cancel.models import SubscriptionCancelIntent
from banking_api.workflows.transfer.engine import TransferWorkflowEngine
from banking_api.workflows.transfer.models import TransferIntent

pytestmark = pytest.mark.postgres
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.fixture
async def postgres_factory():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not configured")
    assert "test" in TEST_DATABASE_URL.lower(), "TEST_DATABASE_URL must name an isolated test DB"
    engine = create_async_engine(TEST_DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE security_guard_states, identity_mappings, mock_bank_transfers, "
                "mock_subscription_cancellations, "
                "events, tasks, messages, "
                "conversations "
                "RESTART IDENTITY CASCADE"
            )
        )
    yield factory
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE security_guard_states, identity_mappings, mock_bank_transfers, "
                "mock_subscription_cancellations, "
                "events, tasks, messages, "
                "conversations "
                "RESTART IDENTITY CASCADE"
            )
        )
    await engine.dispose()


async def test_postgres_migration_persistence_and_fake_agent_e2e(postgres_factory) -> None:
    factory = postgres_factory
    bus = EventBus()
    async with factory() as session:
        revision = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        progress_column = (
            await session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'tasks' AND column_name = 'progress_message'"
                )
            )
        ).scalar()
        executor_columns = set(
            (
                await session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'tasks' "
                        "AND column_name IN ('executor_type', 'executor_id')"
                    )
                )
            ).scalars()
        )
        requested_output_column = (
            await session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'tasks' AND column_name = 'requested_output'"
                )
            )
        ).scalar()
        report_columns = set(
            (
                await session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'reports'"
                    )
                )
            ).scalars()
        )
        workflow_columns = set(
            (
                await session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'workflows'"
                    )
                )
            ).scalars()
        )
        approval_columns = set(
            (
                await session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'approvals'"
                    )
                )
            ).scalars()
        )
        reauth_columns = set(
            (
                await session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'reauthentications'"
                    )
                )
            ).scalars()
        )
        operation_columns = set(
            (
                await session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'operations'"
                    )
                )
            ).scalars()
        )
        provider_ledger_columns = set(
            (
                await session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'mock_bank_transfers'"
                    )
                )
            ).scalars()
        )
        subscription_cancellation_columns = set(
            (
                await session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'mock_subscription_cancellations'"
                    )
                )
            ).scalars()
        )
        outbox_columns = set(
            (
                await session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'outbox_events'"
                    )
                )
            ).scalars()
        )
        task_execution_columns = set(
            (
                await session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'tasks' AND column_name IN "
                        "('next_run_at', 'execution_attempts', 'last_attempt_at', "
                        "'lease_owner', 'lease_expires_at', 'user_id')"
                    )
                )
            ).scalars()
        )
        identity_columns = set(
            (
                await session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'identity_mappings'"
                    )
                )
            ).scalars()
        )
        assert revision == "0017"
        assert progress_column == "progress_message"
        assert executor_columns == {"executor_type", "executor_id"}
        assert requested_output_column == "requested_output"
        assert task_execution_columns == {
            "next_run_at",
            "execution_attempts",
            "last_attempt_at",
            "lease_owner",
            "lease_expires_at",
            "user_id",
        }
        assert identity_columns == {"id", "user_id", "issuer", "subject", "created_at"}
        assert {
            "id",
            "user_id",
            "conversation_id",
            "source_task_id",
            "report_type",
            "report_version",
            "skill_id",
            "skill_version",
            "period",
            "content_json",
            "source_snapshot_hash",
            "created_at",
        }.issubset(report_columns)
        assert {
            "id",
            "user_id",
            "conversation_id",
            "source_task_id",
            "workflow_type",
            "status",
            "version",
            "state_json",
            "created_at",
            "updated_at",
        }.issubset(workflow_columns)
        assert {
            "id",
            "user_id",
            "workflow_id",
            "approval_type",
            "payload_json",
            "payload_hash",
            "status",
            "expires_at",
            "approved_at",
            "invalidated_at",
            "consumed_at",
            "consumed_by_operation_id",
            "created_at",
        }.issubset(approval_columns)
        assert {
            "id",
            "user_id",
            "workflow_id",
            "approval_id",
            "method",
            "status",
            "provider_reference",
            "expires_at",
            "verified_at",
            "attempt_count",
            "created_at",
        }.issubset(reauth_columns)
        assert {
            "id",
            "user_id",
            "workflow_id",
            "approval_id",
            "operation_type",
            "payload_json",
            "payload_hash",
            "idempotency_key",
            "status",
            "version",
            "provider_reference",
            "next_reconcile_at",
            "reconcile_attempts",
            "last_reconcile_at",
            "lease_owner",
            "lease_expires_at",
            "created_at",
            "updated_at",
            "risk_business_date",
        }.issubset(operation_columns)
        assert {
            "provider_reference",
            "idempotency_key",
            "user_id",
            "source_account_id",
            "payee_id",
            "amount",
            "currency",
            "status",
            "error_code",
            "error_message",
            "applied_at",
        }.issubset(provider_ledger_columns)
        assert {
            "provider_reference",
            "user_id",
            "subscription_id",
            "idempotency_key",
            "status",
            "error_code",
            "created_at",
            "completed_at",
        }.issubset(subscription_cancellation_columns)
        assert {
            "id",
            "event_id",
            "created_at",
            "published_at",
            "publish_attempts",
            "next_publish_at",
            "lease_owner",
            "lease_expires_at",
            "last_error_code",
        }.issubset(outbox_columns)
        conversation = await ConversationService(session, bus).create(
            user_id="postgres-test-user", title="PostgreSQL Agent E2E"
        )
    async with factory() as session:
        accepted = await ConversationService(session, bus).accept_message(
            conversation_id=conversation.conversation_id,
            user_id="postgres-test-user",
            content="我的工资卡余额是多少？",
        )

    bank = MockBankService(fixture_user_ids=frozenset({"postgres-test-user"}))
    registry = ToolRegistry()
    registry.register(build_list_accounts_tool(bank))
    registry.register(build_get_balance_tool(bank))
    runtime = AgentRuntime(
        provider=FakeLLMProvider(
            [
                LLMResponse(
                    tool_calls=[LLMToolCall(id="call_1", name="list_accounts", arguments={})]
                ),
                LLMResponse(
                    tool_calls=[
                        LLMToolCall(
                            id="call_2",
                            name="get_balance",
                            arguments={"account_id": "acc_salary"},
                        )
                    ]
                ),
                LLMResponse(content="工资卡余额为 23,864.52 元。"),
            ]
        ),
        registry=registry,
        executor=ToolExecutor(registry, PolicyService()),
        context_builder=ContextBuilder(),
        agent=MINIMAL_BANKING_AGENT,
    )
    runtime_factory = AgentRuntimeFactory()
    runtime_factory.register(RuntimeBackend.MANUAL, runtime)
    await InProcessTaskRunner(factory, bus, runtime_factory).run(accepted.task_id)

    async with factory() as session:
        task = await TaskService(session).get(
            UUID(str(accepted.task_id)), user_id="postgres-test-user"
        )
        detail = await ConversationService(session, bus).get(
            conversation_id=conversation.conversation_id,
            user_id="postgres-test-user",
        )
        events = list(
            (
                await session.execute(
                    select(EventModel)
                    .where(EventModel.task_id == accepted.task_id)
                    .order_by(EventModel.sequence)
                )
            ).scalars()
        )

    assert task.task_type == "BANKING_REQUEST"
    assert task.runtime_backend is RuntimeBackend.MANUAL
    assert task.executor_id == "agent:minimal-banking"
    assert task.status is TaskStatus.COMPLETED
    assert task.version == 8
    assert isinstance(task.input, dict)
    assert {key: value for key, value in task.output.items() if key != "account_results"} == {
        "agent_id": "agent:minimal-banking",
        "assistant_message_id": str(detail.messages[-1].message_id),
        "steps": 3,
        "tool_calls": 2,
        "requested_output": "ANSWER",
    }
    assert task.model_dump(mode="json")["output"]["account_results"][1]["balance"] == "23864.52"
    assert detail.messages[-1].content == "工资卡余额为 23,864.52 元。"
    assert [event.sequence for event in events] == sorted(event.sequence for event in events)
    assert [event.event_type for event in events].count("tool.call.completed") == 2
    assert events[-2].event_type == "task.completed"
    assert events[-1].event_type == "conversation.message.completed"


async def test_postgres_transfer_workflow_persistence_version_and_ownership(
    postgres_factory,
) -> None:
    factory = postgres_factory
    bus = EventBus()
    bank = MockBankService(fixture_user_ids=frozenset({"postgres-transfer-user"}))
    registry = ToolRegistry()
    registry.register(build_list_accounts_tool(bank))
    registry.register(build_get_balance_tool(bank))
    registry.register(build_search_payees_tool(bank))
    engine = TransferWorkflowEngine(ToolExecutor(registry, PolicyService()))
    balances_before = {
        item["account_id"]: bank.get_balance(item["account_id"], user_id="postgres-transfer-user")[
            "balance"
        ]
        for item in bank.list_accounts(user_id="postgres-transfer-user")
    }
    transactions_before = bank.list_transactions(user_id="postgres-transfer-user")

    async with factory() as session:
        conversation = await ConversationService(session, bus).create(
            user_id="postgres-transfer-user", title="PostgreSQL Transfer"
        )
    async with factory() as session:
        accepted = await ConversationService(session, bus).accept_message(
            conversation_id=conversation.conversation_id,
            user_id="postgres-transfer-user",
            content="给张三转2000",
        )
    async with factory() as session:
        created = await WorkflowService(session, bus, engine).create_transfer(
            user_id="postgres-transfer-user",
            conversation_id=conversation.conversation_id,
            source_task_id=accepted.task_id,
            intent=TransferIntent(recipient_query="张三", amount="2000.00"),
        )
    assert created.status.value == "WAITING_FOR_INPUT"
    assert created.version == 2

    async with factory() as session:
        selected_payee = await WorkflowService(session, bus, engine).select_payee(
            created.workflow_id,
            user_id="postgres-transfer-user",
            payee_id="payee_001",
            expected_version=created.version,
        )
    assert selected_payee.version == 3
    assert selected_payee.state["required_input"]["type"] == "SOURCE_ACCOUNT_SELECTION"

    async with factory() as session:
        with pytest.raises(WorkflowVersionConflictError):
            await WorkflowService(session, bus, engine).select_source_account(
                created.workflow_id,
                user_id="postgres-transfer-user",
                account_id="acc_salary",
                expected_version=created.version,
            )
    async with factory() as session:
        ready = await WorkflowService(session, bus, engine).select_source_account(
            created.workflow_id,
            user_id="postgres-transfer-user",
            account_id="acc_salary",
            expected_version=selected_payee.version,
        )
    assert ready.status.value == "READY_FOR_REVIEW"
    assert ready.version == 4

    async with factory() as session:
        approved = await WorkflowService(session, bus, engine).approve(
            ready.workflow_id,
            user_id="postgres-transfer-user",
            expected_version=ready.version,
        )
    assert approved.status.value == "REAUTH_REQUIRED"
    assert approved.version == 5
    assert approved.approval_summary is not None
    assert approved.approval_summary.status is ApprovalStatus.APPROVED

    async with factory() as session:
        with pytest.raises(WorkflowVersionConflictError):
            await WorkflowService(session, bus, engine).approve(
                ready.workflow_id,
                user_id="postgres-transfer-user",
                expected_version=ready.version,
            )
    async with factory() as session:
        challenged = await WorkflowService(session, bus, engine).start_reauthentication(
            ready.workflow_id,
            user_id="postgres-transfer-user",
            expected_version=approved.version,
        )
    assert challenged.version == 6
    assert challenged.reauth_summary is not None
    assert challenged.reauth_summary.status is ReauthenticationStatus.PENDING

    async with factory() as session:
        authorized = await WorkflowService(session, bus, engine).verify_reauthentication(
            ready.workflow_id,
            user_id="postgres-transfer-user",
            reauth_id=challenged.reauth_summary.reauth_id,
            verification_code="246810",
            expected_version=challenged.version,
        )
    assert authorized.status.value == "READY_FOR_COMMIT"
    assert authorized.version == 7
    assert authorized.reauth_summary is not None
    assert authorized.reauth_summary.status is ReauthenticationStatus.VERIFIED

    async with factory() as session:
        recovered = await WorkflowService(session, bus, engine).get(
            ready.workflow_id, user_id="postgres-transfer-user"
        )
        with pytest.raises(WorkflowNotFoundError):
            await WorkflowService(session, bus, engine).get(
                ready.workflow_id, user_id="another-user"
            )
        workflow_events = list(
            (
                await session.execute(
                    select(EventModel).where(
                        EventModel.task_id == accepted.task_id,
                        EventModel.event_type.like("workflow.%"),
                    )
                )
            ).scalars()
        )
        persisted_approval = (
            await session.execute(
                select(ApprovalModel).where(ApprovalModel.workflow_id == ready.workflow_id)
            )
        ).scalar_one()
        persisted_reauth = (
            await session.execute(
                select(ReauthenticationModel).where(
                    ReauthenticationModel.workflow_id == ready.workflow_id
                )
            )
        ).scalar_one()
    assert recovered.state["review_payload"]["amount"] == "2000.00"
    assert recovered.status.value == "READY_FOR_COMMIT"
    assert recovered.approval_summary is not None
    assert recovered.reauth_summary is not None
    assert persisted_approval.payload_json["amount"] == "2000.00"
    assert len(persisted_approval.payload_hash) == 64
    assert persisted_approval.consumed_at is None
    assert persisted_reauth.approval_id == persisted_approval.approval_id
    assert [event.event_type for event in workflow_events] == [
        "workflow.created",
        "workflow.waiting_for_input",
        "workflow.waiting_for_input",
        "workflow.ready_for_review",
        "workflow.risk_evaluated",
        "workflow.risk_evaluated",
        "workflow.reauth_required",
        "workflow.updated",
        "workflow.ready_for_commit",
    ]
    assert all("state_json" not in event.data_json for event in workflow_events)
    assert balances_before == {
        item["account_id"]: bank.get_balance(item["account_id"], user_id="postgres-transfer-user")[
            "balance"
        ]
        for item in bank.list_accounts(user_id="postgres-transfer-user")
    }
    assert bank.list_transactions(user_id="postgres-transfer-user") == transactions_before

    async with factory() as session:
        mutated = await WorkflowService(session, bus, engine).set_amount(
            ready.workflow_id,
            user_id="postgres-transfer-user",
            amount=Decimal("20000.00"),
            expected_version=authorized.version,
        )
    assert mutated.status.value == "READY_FOR_REVIEW"
    assert mutated.state["authorization"] is None
    assert mutated.approval_summary is not None
    assert mutated.approval_summary.status is ApprovalStatus.INVALIDATED
    assert mutated.reauth_summary is not None
    assert mutated.reauth_summary.status is ReauthenticationStatus.INVALIDATED


async def test_postgres_operation_atomic_consumption_and_restart_recovery(
    postgres_factory,
) -> None:
    factory = postgres_factory
    bus = EventBus()
    user_id = "postgres-operation-user"
    bank = MockBankService(fixture_user_ids=frozenset({user_id}))
    provider = MockTransferProvider(factory, bank)
    registry = ToolRegistry()
    registry.register(build_list_accounts_tool(bank))
    registry.register(build_get_balance_tool(bank, provider.effective_balance))
    registry.register(build_search_payees_tool(bank))
    registry.register(build_commit_transfer_tool(factory, provider))
    registry.register(build_get_transfer_status_tool(factory, provider))
    engine = TransferWorkflowEngine(ToolExecutor(registry, PolicyService()))

    async with factory() as session:
        conversation = await ConversationService(session, bus).create(
            user_id=user_id, title="PostgreSQL Operation"
        )
    async with factory() as session:
        accepted = await ConversationService(session, bus).accept_message(
            conversation_id=conversation.conversation_id,
            user_id=user_id,
            content="给张三转2000",
        )
    async with factory() as session:
        workflow = await WorkflowService(session, bus, engine).create_transfer(
            user_id=user_id,
            conversation_id=conversation.conversation_id,
            source_task_id=accepted.task_id,
            intent=TransferIntent(recipient_query="张三", amount="2000.00"),
        )
    async with factory() as session:
        workflow = await WorkflowService(session, bus, engine).select_payee(
            workflow.workflow_id,
            user_id=user_id,
            payee_id="payee_001",
            expected_version=workflow.version,
        )
    async with factory() as session:
        workflow = await WorkflowService(session, bus, engine).select_source_account(
            workflow.workflow_id,
            user_id=user_id,
            account_id="acc_salary",
            expected_version=workflow.version,
        )
    async with factory() as session:
        workflow = await WorkflowService(session, bus, engine).approve(
            workflow.workflow_id,
            user_id=user_id,
            expected_version=workflow.version,
        )
    async with factory() as session:
        workflow = await WorkflowService(session, bus, engine).start_reauthentication(
            workflow.workflow_id,
            user_id=user_id,
            expected_version=workflow.version,
        )
    async with factory() as session:
        workflow = await WorkflowService(session, bus, engine).verify_reauthentication(
            workflow.workflow_id,
            user_id=user_id,
            reauth_id=workflow.reauth_summary.reauth_id,  # type: ignore[union-attr]
            verification_code="246810",
            expected_version=workflow.version,
        )

    initial_balance = await provider.effective_balance(user_id, "acc_salary")
    async with factory() as session:
        created = await OperationService(session, bus, engine).prepare_transfer(
            workflow.workflow_id,
            user_id=user_id,
            expected_version=workflow.version,
        )
    assert created.status is OperationStatus.CREATED
    async with factory() as session:
        persisted_created = await session.get(OperationModel, created.operation_id)
        approval = await session.get(
            ApprovalModel,
            workflow.approval_summary.approval_id,  # type: ignore[union-attr]
        )
    stable_key = persisted_created.idempotency_key  # type: ignore[union-attr]
    assert approval.status is ApprovalStatus.CONSUMED  # type: ignore[union-attr]
    assert approval.consumed_by_operation_id == created.operation_id  # type: ignore[union-attr]

    # New sessions model an application restart after the atomic CREATED boundary.
    async with factory() as session:
        succeeded = await OperationService(session, bus, engine).reconcile(
            created.operation_id,
            user_id=user_id,
            expected_version=created.version,
        )
    assert succeeded.status is OperationStatus.SUCCEEDED
    assert await provider.effective_balance(user_id, "acc_salary") == initial_balance - Decimal(
        "2000.00"
    )
    assert await provider.transfer_count() == 1
    async with factory() as session:
        recovered = await session.get(OperationModel, created.operation_id)
        with pytest.raises(OperationNotFoundError):
            await OperationService(session, bus, engine).get(
                created.operation_id, user_id="other-user"
            )
    assert recovered.idempotency_key == stable_key  # type: ignore[union-attr]
    assert recovered.payload_hash == approval.payload_hash  # type: ignore[union-attr]


async def _create_postgres_created_operation(
    factory,
    bus,
    *,
    user_id,
    amount="2000.00",
    bank=None,
    provider=None,
    engine=None,
):  # type: ignore[no-untyped-def]
    bank = bank or MockBankService(fixture_user_ids=frozenset({user_id}))
    provider = provider or MockTransferProvider(factory, bank)
    if engine is None:
        registry = ToolRegistry()
        registry.register(build_list_accounts_tool(bank))
        registry.register(build_get_balance_tool(bank, provider.effective_balance))
        registry.register(build_search_payees_tool(bank))
        registry.register(build_commit_transfer_tool(factory, provider))
        registry.register(build_get_transfer_status_tool(factory, provider))
        engine = TransferWorkflowEngine(ToolExecutor(registry, PolicyService()))
    async with factory() as session:
        conversation = await ConversationService(session, bus).create(
            user_id=user_id, title="PostgreSQL Recovery Claim"
        )
    async with factory() as session:
        accepted = await ConversationService(session, bus).accept_message(
            conversation_id=conversation.conversation_id,
            user_id=user_id,
            content=f"给张三转{amount}",
        )
    async with factory() as session:
        workflow = await WorkflowService(session, bus, engine).create_transfer(
            user_id=user_id,
            conversation_id=conversation.conversation_id,
            source_task_id=accepted.task_id,
            intent=TransferIntent(recipient_query="张三", amount=amount),
        )
    async with factory() as session:
        workflow = await WorkflowService(session, bus, engine).select_payee(
            workflow.workflow_id,
            user_id=user_id,
            payee_id="payee_001",
            expected_version=workflow.version,
        )
    async with factory() as session:
        workflow = await WorkflowService(session, bus, engine).select_source_account(
            workflow.workflow_id,
            user_id=user_id,
            account_id="acc_salary",
            expected_version=workflow.version,
        )
    async with factory() as session:
        workflow = await WorkflowService(session, bus, engine).approve(
            workflow.workflow_id,
            user_id=user_id,
            expected_version=workflow.version,
        )
    async with factory() as session:
        workflow = await WorkflowService(session, bus, engine).start_reauthentication(
            workflow.workflow_id,
            user_id=user_id,
            expected_version=workflow.version,
        )
    async with factory() as session:
        workflow = await WorkflowService(session, bus, engine).verify_reauthentication(
            workflow.workflow_id,
            user_id=user_id,
            reauth_id=workflow.reauth_summary.reauth_id,  # type: ignore[union-attr]
            verification_code="246810",
            expected_version=workflow.version,
        )
    async with factory() as session:
        created = await OperationService(session, bus, engine).prepare_transfer(
            workflow.workflow_id,
            user_id=user_id,
            expected_version=workflow.version,
        )
    return bank, provider, engine, created


class FixedSalaryBalanceBank(MockBankService):
    def get_balance(self, account_id: str, *, user_id: str):  # type: ignore[no-untyped-def]
        result = super().get_balance(account_id, user_id=user_id)
        if account_id == "acc_salary":
            result["balance"] = Decimal("10000.00")
        return result


async def test_postgres_provider_rejects_stale_precheck_and_recovery_replays_exactly_once(
    postgres_factory,
) -> None:
    factory = postgres_factory
    bus = RecordingPostgresEventBus()
    user_id = "concurrent-operation-owner"
    bank = FixedSalaryBalanceBank(fixture_user_ids=frozenset({user_id}))
    provider = MockTransferProvider(factory, bank)
    registry = ToolRegistry()
    registry.register(build_list_accounts_tool(bank))
    registry.register(build_get_balance_tool(bank, provider.effective_balance))
    registry.register(build_search_payees_tool(bank))
    registry.register(build_commit_transfer_tool(factory, provider))
    registry.register(build_get_transfer_status_tool(factory, provider))
    engine = TransferWorkflowEngine(ToolExecutor(registry, PolicyService()))

    _, _, _, created_a = await _create_postgres_created_operation(
        factory,
        bus,
        user_id=user_id,
        amount="8000.00",
        bank=bank,
        provider=provider,
        engine=engine,
    )
    _, _, _, created_b = await _create_postgres_created_operation(
        factory,
        bus,
        user_id=user_id,
        amount="8000.00",
        bank=bank,
        provider=provider,
        engine=engine,
    )

    async with factory() as session:
        operation_a = await session.get(OperationModel, created_a.operation_id)
        payload_a = operation_a.payload_json  # type: ignore[union-attr]
        key_a = operation_a.idempotency_key  # type: ignore[union-attr]
    accepted_a = await provider.submit_transfer(
        TransferProviderRequest(
            user_id=user_id,
            idempotency_key=key_a,
            source_account_id=payload_a["source_account_id"],
            payee_id=payload_a["payee_id"],
            amount=payload_a["amount"],
            currency=payload_a["currency"],
        )
    )
    assert accepted_a.outcome.value == "ACCEPTED"

    # Operation B passed the earlier Workflow check while the owner's balance was
    # 10,000. Provider now sees Operation A's durable 8,000 debit and rejects B.
    async with factory() as session:
        failed_b = await OperationService(session, bus, engine).reconcile(
            created_b.operation_id,
            user_id=user_id,
            expected_version=created_b.version,
        )
    assert failed_b.status is OperationStatus.FAILED
    assert failed_b.error_code == "INSUFFICIENT_FUNDS"

    # Application A had crashed before persisting provider success. Recovery
    # replays the same key and converges without a second debit.
    policy = OperationRecoveryPolicy(
        lease_duration=timedelta(seconds=30),
        initial_retry_delay=timedelta(seconds=1),
        maximum_retry_delay=timedelta(seconds=8),
        backoff_multiplier=2,
    )
    worker = OperationRecoveryWorker(
        factory,
        bus,
        engine,
        policy=policy,
        poll_interval_seconds=0.01,
        batch_size=10,
        worker_id="concurrency-recovery-worker",
    )
    assert await worker.run_once() == 1
    assert await provider.effective_balance(user_id, "acc_salary") == Decimal("2000.00")
    assert await provider.transfer_count() == 2  # one succeeded fact + one failed fact

    outbox_publisher = OutboxPublisher(
        factory,
        bus,
        policy=outbox_policy(),
        poll_interval_seconds=0.01,
        batch_size=100,
        publisher_id="operation-event-publisher",
    )
    assert await outbox_publisher.run_once() > 0
    assert any(
        event.event_type == "operation.succeeded"
        and event.data["operation_id"] == str(created_a.operation_id)
        for event in bus.published
    )
    assert await provider.transfer_count() == 2

    async with factory() as session:
        workflow_a = await session.get(WorkflowModel, created_a.workflow_id)
        workflow_b = await session.get(WorkflowModel, created_b.workflow_id)
        recovered_a = await session.get(OperationModel, created_a.operation_id)
        successful_provider_rows = await session.scalar(
            select(func.count())
            .select_from(MockBankTransferModel)
            .where(MockBankTransferModel.status == "SUCCEEDED")
        )
    assert workflow_a.status is WorkflowStatus.SUCCEEDED  # type: ignore[union-attr]
    assert workflow_b.status is WorkflowStatus.FAILED  # type: ignore[union-attr]
    assert recovered_a.status is OperationStatus.SUCCEEDED  # type: ignore[union-attr]
    assert recovered_a.provider_reference == accepted_a.provider_reference  # type: ignore[union-attr]
    assert successful_provider_rows == 1


async def test_postgres_skip_locked_lease_expiry_and_exact_once_recovery(
    postgres_factory,
) -> None:
    factory = postgres_factory
    bus = EventBus()
    bank, provider, engine, created = await _create_postgres_created_operation(
        factory, bus, user_id="postgres-claim-user"
    )
    initial_balance = Decimal(
        str(bank.get_balance("acc_salary", user_id="postgres-claim-user")["balance"])
    )
    now = datetime.now(UTC)
    lease_duration = timedelta(seconds=30)

    # Session A keeps the PostgreSQL row lock open. Session B must skip it rather
    # than wait or claim the same Operation.
    async with factory() as session_a, factory() as session_b:
        claims_a = await OperationRepository(session_a).claim_due(
            lease_owner="worker-a",
            now=now,
            lease_expires_at=now + lease_duration,
            limit=1,
        )
        claims_b = await OperationRepository(session_b).claim_due(
            lease_owner="worker-b",
            now=now,
            lease_expires_at=now + lease_duration,
            limit=1,
        )
        assert [claim.operation_id for claim in claims_a] == [created.operation_id]
        assert claims_b == []
        await session_b.rollback()
        await session_a.commit()

    # Model a provider accept followed by worker A crashing before local status
    # persistence. The application row remains CREATED and retains A's lease.
    async with factory() as session:
        operation = await session.get(OperationModel, created.operation_id)
        stable_key = operation.idempotency_key  # type: ignore[union-attr]
        payload = operation.payload_json  # type: ignore[union-attr]
    await provider.submit_transfer(
        TransferProviderRequest(
            user_id="postgres-claim-user",
            idempotency_key=stable_key,
            source_account_id=payload["source_account_id"],
            payee_id=payload["payee_id"],
            amount=payload["amount"],
            currency=payload["currency"],
        )
    )

    async with factory() as session:
        active_lease_claims = await OperationRepository(session).claim_due(
            lease_owner="worker-b",
            now=now + timedelta(seconds=1),
            lease_expires_at=now + timedelta(seconds=31),
            limit=1,
        )
        assert active_lease_claims == []
        await session.rollback()

    reclaimed_at = now + timedelta(seconds=31)
    async with factory() as session:
        reclaimed = await OperationRepository(session).claim_due(
            lease_owner="worker-b",
            now=reclaimed_at,
            lease_expires_at=reclaimed_at + lease_duration,
            limit=1,
        )
        await session.commit()
    assert len(reclaimed) == 1
    assert reclaimed[0].operation_id == created.operation_id
    assert reclaimed[0].reclaimed is True

    async with factory() as session:
        with pytest.raises(OperationLeaseLostError):
            await OperationService(session, bus, engine).reconcile_claimed(
                created.operation_id, lease_owner="worker-a"
            )

    policy = OperationRecoveryPolicy(
        lease_duration=lease_duration,
        initial_retry_delay=timedelta(seconds=1),
        maximum_retry_delay=timedelta(seconds=8),
        backoff_multiplier=2,
    )
    async with factory() as session:
        recovered = await OperationService(
            session, bus, engine, recovery_policy=policy
        ).reconcile_claimed(created.operation_id, lease_owner="worker-b")
    assert recovered.status is OperationStatus.SUCCEEDED
    assert await provider.transfer_count() == 1
    assert await provider.effective_balance(
        "postgres-claim-user", "acc_salary"
    ) == initial_balance - Decimal("2000.00")
    async with factory() as session:
        persisted = await session.get(OperationModel, created.operation_id)
        terminal_claims = await OperationRepository(session).claim_due(
            lease_owner="worker-c",
            now=reclaimed_at + timedelta(minutes=1),
            lease_expires_at=reclaimed_at + timedelta(minutes=2),
            limit=1,
        )
    assert persisted.idempotency_key == stable_key  # type: ignore[union-attr]
    assert persisted.reconcile_attempts == 1  # type: ignore[union-attr]
    assert persisted.next_reconcile_at is None  # type: ignore[union-attr]
    assert persisted.lease_owner is None  # type: ignore[union-attr]
    assert terminal_claims == []


async def test_postgres_report_artifact_round_trip(postgres_factory) -> None:
    factory = postgres_factory
    bus = EventBus()
    async with factory() as session:
        service = ConversationService(
            session,
            bus,
            runtime_backend=RuntimeBackend.LANGGRAPH,
        )
        conversation = await service.create(
            user_id="postgres-test-user",
            title="PostgreSQL Report",
        )
        accepted = await service.accept_message(
            conversation_id=conversation.conversation_id,
            user_id="postgres-test-user",
            content="生成2026年8月消费报告",
        )

    analytics = FinancialAnalyticsService(MockBankService())
    snapshot = FinancialAnalysisSnapshot(
        period="2026-08",
        account_ids=[],
        spending_summary=analytics.spending_summary("2026-08", user_id="dev-user-001"),
        category_breakdown=analytics.category_breakdown("2026-08", user_id="dev-user-001"),
        period_comparison=analytics.compare_periods("2026-08", user_id="dev-user-001"),
        top_transactions=analytics.top_transactions("2026-08", 5, user_id="dev-user-001"),
        tool_evidence=[
            ToolEvidence(
                capability_id="transaction.spending_summary",
                input={"month": "2026-08"},
            ),
            ToolEvidence(
                capability_id="transaction.category_breakdown",
                input={"month": "2026-08"},
            ),
            ToolEvidence(
                capability_id="transaction.compare_periods",
                input={"month": "2026-08"},
            ),
            ToolEvidence(
                capability_id="transaction.top_transactions",
                input={"month": "2026-08", "limit": 5},
            ),
        ],
    )
    narrative = LLMResponse(
        content=json.dumps(
            {
                "headline": "本月支出上升且结构集中",
                "insights": [
                    {
                        "type": "STRUCTURE",
                        "title": "住房是最主要的支出类别",
                        "narrative": "消费结构主要由住房、购物和旅行构成。",
                        "evidence_refs": ["category_breakdown.HOUSING.share"],
                    },
                    {
                        "type": "CHANGE",
                        "title": "旅行和购物是主要增量来源",
                        "narrative": "本月支出明显上升，旅行和购物的变化最突出。",
                        "evidence_refs": [
                            "category_breakdown.TRAVEL.absolute_change",
                            "category_breakdown.SHOPPING.absolute_change",
                        ],
                    },
                ],
            },
            ensure_ascii=False,
        )
    )
    report = await SkillExecutor(FakeLLMProvider([narrative])).execute(snapshot)

    async with factory() as session:
        service = ReportService(session)
        created = await service.create_report(
            user_id="postgres-test-user",
            conversation_id=conversation.conversation_id,
            source_task_id=accepted.task_id,
            report=report,
            snapshot=snapshot,
            skill=MonthlySpendingReportSkill.definition,
        )
        await session.commit()
    async with factory() as session:
        loaded = await ReportService(session).get_report_for_user(
            created.report_id,
            user_id="postgres-test-user",
        )

    assert loaded.content.overview.total_spending_display == "¥16,547.30"
    assert str(loaded.content.overview.total_spending) == "16547.30"
    assert loaded.source_snapshot_hash == created.source_snapshot_hash


class CountingBankService(MockBankService):
    def __init__(self, counts: dict[str, int]) -> None:
        super().__init__()
        self.counts = counts

    def list_accounts(self, *, user_id: str):  # type: ignore[no-untyped-def]
        self.counts["list_accounts"] += 1
        return super().list_accounts(user_id=user_id)

    def get_balance(self, account_id: str, *, user_id: str):  # type: ignore[no-untyped-def]
        self.counts["get_balance"] += 1
        return super().get_balance(account_id, user_id=user_id)


def build_langgraph_runtime(provider, bank, checkpointer):  # type: ignore[no-untyped-def]
    registry = ToolRegistry()
    registry.register(build_list_accounts_tool(bank))
    registry.register(build_get_balance_tool(bank))
    return LangGraphAgentRuntime(
        provider=provider,
        registry=registry,
        executor=ToolExecutor(registry, PolicyService()),
        context_builder=ContextBuilder(),
        agent=MINIMAL_BANKING_AGENT,
        checkpointer=checkpointer,
    )


async def test_postgres_checkpoint_persistence_and_resume(postgres_factory) -> None:
    assert TEST_DATABASE_URL is not None
    checkpoint_url = normalize_checkpoint_database_url(TEST_DATABASE_URL)
    task_id = uuid4()
    conversation_id = uuid4()
    message = Message(
        message_id=uuid4(),
        conversation_id=conversation_id,
        role=MessageRole.USER,
        content="我的工资卡余额是多少？",
        created_at=datetime.now(UTC),
    )
    request = AgentRunRequest(
        task_id=task_id,
        conversation_id=conversation_id,
        current_task=message.content,
        conversation_messages=[message],
        principal=ExecutionPrincipal.for_task("dev-user-001"),
    )
    counts = {"list_accounts": 0, "get_balance": 0}

    manager_one = LangGraphCheckpointManager(checkpoint_url, strict_msgpack=True)
    saver_one = await manager_one.start()
    runtime_one = build_langgraph_runtime(
        FakeLLMProvider(
            [LLMResponse(tool_calls=[LLMToolCall(id="list", name="list_accounts", arguments={})])]
        ),
        CountingBankService(counts),
        saver_one,
    )
    phase_one = await runtime_one.run_until_tool_checkpoint(request)
    assert phase_one["tool_call_count"] == 1
    assert counts == {"list_accounts": 1, "get_balance": 0}

    async with postgres_factory() as session:
        persisted = (
            await session.execute(
                text("SELECT count(*) FROM checkpoints WHERE thread_id = :thread_id"),
                {"thread_id": str(task_id)},
            )
        ).scalar_one()
    assert persisted > 0
    await manager_one.close()
    del runtime_one

    manager_two = LangGraphCheckpointManager(checkpoint_url, strict_msgpack=True)
    saver_two = await manager_two.start()
    runtime_two = build_langgraph_runtime(
        FakeLLMProvider(
            [
                LLMResponse(
                    tool_calls=[
                        LLMToolCall(
                            id="balance",
                            name="get_balance",
                            arguments={"account_id": "acc_salary"},
                        )
                    ]
                ),
                LLMResponse(content="工资卡余额为 23,864.52 元。"),
            ]
        ),
        CountingBankService(counts),
        saver_two,
    )
    result = await runtime_two.resume(request)
    assert result.answer == "工资卡余额为 23,864.52 元。"
    assert counts == {"list_accounts": 1, "get_balance": 1}
    tuple_ = await saver_two.aget_tuple({"configurable": {"thread_id": str(task_id)}})
    assert tuple_ is not None
    checkpoint_repr = repr(tuple_.checkpoint).lower()
    for forbidden in (
        "llm_api_key",
        "database_url",
        "chain_of_thought",
        "scratchpad",
    ):
        assert forbidden not in checkpoint_repr
    await manager_two.close()


async def test_postgres_startup_reconciliation(postgres_factory) -> None:
    factory = postgres_factory
    bus = EventBus()
    async with factory() as session:
        conversation = await ConversationService(session, bus).create(
            user_id="postgres-test-user", title="Reconciliation"
        )
        tasks = TaskRepository(session)
        pending = await tasks.create(
            conversation_id=conversation.conversation_id,
            user_id="postgres-test-user",
            task_type="MINIMAL_AGENT_RUN",
            input_data={},
            runtime_backend=RuntimeBackend.LANGGRAPH,
        )
        running = await tasks.create(
            conversation_id=conversation.conversation_id,
            user_id="postgres-test-user",
            task_type="MINIMAL_AGENT_RUN",
            input_data={},
        )
        completed = await tasks.create(
            conversation_id=conversation.conversation_id,
            user_id="postgres-test-user",
            task_type="MINIMAL_AGENT_RUN",
            input_data={},
        )
        await tasks.transition(running, TaskStatus.RUNNING)
        await tasks.transition(completed, TaskStatus.COMPLETED)
        pending.next_run_at = None
        running.next_run_at = None
        ids = [pending.task_id, running.task_id, completed.task_id]
        await session.commit()

    assert await TaskReconciliationService(factory, bus).reconcile() == 2
    async with factory() as session:
        tasks = TaskRepository(session)
        reconciled = [await tasks.get(task_id) for task_id in ids]
        assert [task.status for task in reconciled if task is not None] == [
            TaskStatus.PENDING,
            TaskStatus.RUNNING,
            TaskStatus.COMPLETED,
        ]
        assert reconciled[0] is not None
        assert reconciled[0].runtime_backend is RuntimeBackend.LANGGRAPH
        assert reconciled[0].next_run_at is not None
        assert reconciled[1] is not None and reconciled[1].next_run_at is not None


class RecordingPostgresEventBus(EventBus):
    def __init__(self, *, failures: int = 0) -> None:
        super().__init__()
        self.failures = failures
        self.published = []

    async def publish(self, event):  # type: ignore[no-untyped-def]
        if self.failures:
            self.failures -= 1
            raise RuntimeError("temporary event bus failure")
        self.published.append(event)
        await super().publish(event)


def outbox_policy(*, lease_seconds: float = 2) -> OutboxPublicationPolicy:
    return OutboxPublicationPolicy(
        lease_duration=timedelta(seconds=lease_seconds),
        initial_retry_delay=timedelta(seconds=1),
        maximum_retry_delay=timedelta(seconds=8),
        backoff_multiplier=2,
    )


async def create_postgres_outbox_event(factory, bus, *, event_type="test.outbox"):
    async with factory() as session:  # type: ignore[no-untyped-def]
        conversation = await ConversationService(session, bus).create(
            user_id="postgres-outbox-user", title="PostgreSQL Outbox"
        )
        event = await EventPublisher(session).persist(
            event_type=event_type,
            conversation_id=conversation.conversation_id,
            task_id=None,
            data={"business_version": 1},
        )
        await session.commit()
    return conversation, event


async def test_postgres_event_outbox_commit_then_publisher_recovers(postgres_factory) -> None:
    factory = postgres_factory
    bus = RecordingPostgresEventBus()
    conversation, event = await create_postgres_outbox_event(factory, bus)

    async with factory() as session:
        outbox = (
            await session.execute(
                select(OutboxEventModel).where(OutboxEventModel.event_id == event.event_id)
            )
        ).scalar_one()
        conversation_count = await session.scalar(
            select(func.count())
            .select_from(ConversationModel)
            .where(ConversationModel.conversation_id == conversation.conversation_id)
        )
    assert outbox.published_at is None
    assert bus.published == []
    assert conversation_count == 1

    async with factory() as session:
        with pytest.raises(IntegrityError):
            await OutboxRepository(session).enqueue(
                event_id=event.event_id,
                next_publish_at=datetime.now(UTC),
            )
        await session.rollback()

    publisher = OutboxPublisher(
        factory,
        bus,
        policy=outbox_policy(),
        poll_interval_seconds=0.01,
        batch_size=10,
        publisher_id="postgres-restart-publisher",
    )
    assert await publisher.run_once() == 1
    assert [item.event_id for item in bus.published] == [event.event_id]
    async with factory() as session:
        published = await session.get(OutboxEventModel, outbox.outbox_id)
    assert published is not None and published.published_at is not None
    assert published.next_publish_at is None
    assert await publisher.run_once() == 0


async def test_postgres_two_publishers_skip_locked_and_reclaim_expired_lease(
    postgres_factory,
) -> None:
    factory = postgres_factory
    bus = EventBus()
    _, event = await create_postgres_outbox_event(factory, bus)
    now = datetime.now(UTC)

    async with factory() as session_a, factory() as session_b:
        claims_a = await OutboxRepository(session_a).claim_due(
            lease_owner="publisher-a",
            now=now,
            lease_expires_at=now + timedelta(seconds=30),
            limit=1,
        )
        claims_b = await OutboxRepository(session_b).claim_due(
            lease_owner="publisher-b",
            now=now,
            lease_expires_at=now + timedelta(seconds=30),
            limit=1,
        )
        assert [claim.event_id for claim in claims_a] == [event.event_id]
        assert claims_b == []
        await session_b.rollback()
        await session_a.commit()

    async with factory() as session:
        active = await OutboxRepository(session).claim_due(
            lease_owner="publisher-b",
            now=now + timedelta(seconds=1),
            lease_expires_at=now + timedelta(seconds=31),
            limit=1,
        )
        assert active == []
        await session.rollback()

    async with factory() as session:
        reclaimed = await OutboxRepository(session).claim_due(
            lease_owner="publisher-b",
            now=now + timedelta(seconds=31),
            lease_expires_at=now + timedelta(seconds=61),
            limit=1,
        )
        await session.commit()
    assert len(reclaimed) == 1
    assert reclaimed[0].event_id == event.event_id
    assert reclaimed[0].reclaimed is True
    assert reclaimed[0].attempt == 2


async def test_postgres_publish_before_ack_crash_duplicates_only_notification(
    postgres_factory, monkeypatch
) -> None:
    factory = postgres_factory
    bus = RecordingPostgresEventBus()
    conversation, event = await create_postgres_outbox_event(factory, bus)
    clock = [datetime.now(UTC)]
    first = OutboxPublisher(
        factory,
        bus,
        policy=outbox_policy(lease_seconds=1),
        poll_interval_seconds=0.01,
        batch_size=1,
        publisher_id="postgres-publisher-a",
        clock=lambda: clock[0],
    )

    async def crash_before_ack(_claim):  # type: ignore[no-untyped-def]
        raise RuntimeError("crash before outbox acknowledgement")

    monkeypatch.setattr(first, "_mark_published", crash_before_ack)
    with pytest.raises(RuntimeError, match="crash before"):
        await first.run_once()

    clock[0] += timedelta(seconds=2)
    second = OutboxPublisher(
        factory,
        bus,
        policy=outbox_policy(lease_seconds=1),
        poll_interval_seconds=0.01,
        batch_size=1,
        publisher_id="postgres-publisher-b",
        clock=lambda: clock[0],
    )
    assert await second.run_once() == 1
    assert [item.event_id for item in bus.published] == [event.event_id, event.event_id]

    async with factory() as session:
        event_count = await session.scalar(
            select(func.count())
            .select_from(EventModel)
            .where(EventModel.event_id == event.event_id)
        )
        outbox_rows = list(
            (
                await session.execute(
                    select(OutboxEventModel).where(OutboxEventModel.event_id == event.event_id)
                )
            ).scalars()
        )
        conversation_count = await session.scalar(
            select(func.count())
            .select_from(ConversationModel)
            .where(ConversationModel.conversation_id == conversation.conversation_id)
        )
    assert event_count == 1
    assert len(outbox_rows) == 1
    assert outbox_rows[0].published_at is not None
    assert outbox_rows[0].publish_attempts == 2
    assert conversation_count == 1


async def test_postgres_event_bus_failure_schedules_retry(postgres_factory) -> None:
    factory = postgres_factory
    bus = RecordingPostgresEventBus(failures=1)
    _, event = await create_postgres_outbox_event(factory, bus)
    clock = [datetime.now(UTC)]
    publisher = OutboxPublisher(
        factory,
        bus,
        policy=outbox_policy(),
        poll_interval_seconds=0.01,
        batch_size=1,
        publisher_id="postgres-retry-publisher",
        clock=lambda: clock[0],
    )
    assert await publisher.run_once() == 1
    async with factory() as session:
        retry = (
            await session.execute(
                select(OutboxEventModel).where(OutboxEventModel.event_id == event.event_id)
            )
        ).scalar_one()
    assert retry.published_at is None
    assert retry.publish_attempts == 1
    assert retry.last_error_code == "EVENT_BUS_PUBLISH_FAILED"
    assert retry.lease_owner is None

    clock[0] += timedelta(seconds=1)
    assert await publisher.run_once() == 1
    async with factory() as session:
        published = await session.get(OutboxEventModel, retry.outbox_id)
    assert published is not None and published.published_at is not None
    assert published.publish_attempts == 2
    assert [item.event_id for item in bus.published] == [event.event_id]


def task_execution_policy(*, lease_seconds: float = 30) -> TaskExecutionPolicy:
    return TaskExecutionPolicy(
        lease_duration=timedelta(seconds=lease_seconds),
        heartbeat_interval=timedelta(seconds=max(lease_seconds / 4, 0.01)),
        initial_retry_delay=timedelta(seconds=1),
        maximum_retry_delay=timedelta(seconds=8),
        backoff_multiplier=2,
    )


async def create_postgres_task(factory, bus):  # type: ignore[no-untyped-def]
    async with factory() as session:
        conversation = await ConversationService(session, bus).create(
            user_id="postgres-task-worker", title="Durable Task"
        )
    async with factory() as session:
        accepted = await ConversationService(session, bus).accept_message(
            conversation_id=conversation.conversation_id,
            user_id="postgres-task-worker",
            content="查询工资卡余额",
        )
    return conversation, accepted


async def test_postgres_two_task_workers_skip_locked_heartbeat_and_fencing(
    postgres_factory,
) -> None:
    factory = postgres_factory
    bus = EventBus()
    _, accepted = await create_postgres_task(factory, bus)
    now = datetime.now(UTC)

    async with factory() as session_a, factory() as session_b:
        claims_a = await TaskRepository(session_a).claim_due(
            lease_owner="task-worker-a",
            now=now,
            lease_expires_at=now + timedelta(seconds=30),
            limit=1,
        )
        claims_b = await TaskRepository(session_b).claim_due(
            lease_owner="task-worker-b",
            now=now,
            lease_expires_at=now + timedelta(seconds=30),
            limit=1,
        )
        assert len(claims_a) == 1
        assert claims_b == []
        await session_b.rollback()
        await session_a.commit()
    claim_a = claims_a[0]

    async with factory() as session:
        renewed = await TaskRepository(session).renew_lease(
            task_id=accepted.task_id,
            lease_owner="task-worker-a",
            attempt=claim_a.attempt,
            now=now + timedelta(seconds=1),
            lease_expires_at=now + timedelta(seconds=60),
        )
        await session.commit()
    assert renewed is True

    async with factory() as session:
        active = await TaskRepository(session).claim_due(
            lease_owner="task-worker-b",
            now=now + timedelta(seconds=31),
            lease_expires_at=now + timedelta(seconds=61),
            limit=1,
        )
        await session.rollback()
    assert active == []

    async with factory() as session:
        reclaimed = await TaskRepository(session).claim_due(
            lease_owner="task-worker-b",
            now=now + timedelta(seconds=61),
            lease_expires_at=now + timedelta(seconds=91),
            limit=1,
        )
        await session.commit()
    assert len(reclaimed) == 1
    claim_b = reclaimed[0]
    assert claim_b.reclaimed is True
    assert claim_b.attempt == claim_a.attempt + 1

    async with factory() as session:
        stale = await TaskRepository(session).get_owned(
            task_id=accepted.task_id,
            lease_owner=claim_a.lease_owner,
            attempt=claim_a.attempt,
            now=now + timedelta(seconds=62),
            for_update=True,
        )
        current = await TaskRepository(session).get_owned(
            task_id=accepted.task_id,
            lease_owner=claim_b.lease_owner,
            attempt=claim_b.attempt,
            now=now + timedelta(seconds=62),
            for_update=True,
        )
        await session.rollback()
    assert stale is None
    assert current is not None


class CompletingTaskExecutor:
    def __init__(self, factory) -> None:  # type: ignore[no-untyped-def]
        self.factory = factory
        self.calls = 0

    async def execute_claimed(self, claim, *, policy):  # type: ignore[no-untyped-def]
        self.calls += 1
        async with self.factory() as session:
            tasks = TaskRepository(session)
            task = await tasks.get_owned(
                task_id=claim.task_id,
                lease_owner=claim.lease_owner,
                attempt=claim.attempt,
                now=datetime.now(UTC),
                for_update=True,
            )
            if task is None:
                raise TaskLeaseLostError
            await tasks.transition(task, TaskStatus.COMPLETED, output={"recovered": True})
            await EventPublisher(session).persist(
                event_type="task.completed",
                conversation_id=claim.conversation_id,
                task_id=claim.task_id,
                data={"status": task.status.value, "version": task.version},
            )
            await session.commit()


async def test_postgres_task_worker_crash_lease_expiry_and_recovery(
    postgres_factory,
) -> None:
    factory = postgres_factory
    bus = EventBus()
    _, accepted = await create_postgres_task(factory, bus)
    now = datetime.now(UTC)
    async with factory() as session:
        crashed = await TaskRepository(session).claim_due(
            lease_owner="crashed-task-worker",
            now=now,
            lease_expires_at=now + timedelta(seconds=1),
            limit=1,
        )
        await session.commit()
    assert len(crashed) == 1

    async with factory() as session:
        task = await session.get(TaskModel, accepted.task_id)
        assert task is not None
        task.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    executor = CompletingTaskExecutor(factory)
    worker = TaskExecutionWorker(
        factory,
        executor,
        policy=task_execution_policy(),
        poll_interval_seconds=0.01,
        batch_size=1,
        max_concurrency=1,
        worker_id="recovery-task-worker",
    )
    assert await worker.run_task_once(accepted.task_id) is True
    assert executor.calls == 1

    async with factory() as session:
        task = await session.get(TaskModel, accepted.task_id)
        event_count = await session.scalar(
            select(func.count())
            .select_from(EventModel)
            .where(
                EventModel.task_id == accepted.task_id,
                EventModel.event_type == "task.completed",
            )
        )
        outbox_count = await session.scalar(
            select(func.count())
            .select_from(OutboxEventModel)
            .join(EventModel, EventModel.event_id == OutboxEventModel.event_id)
            .where(
                EventModel.task_id == accepted.task_id,
                EventModel.event_type == "task.completed",
            )
        )
    assert task is not None and task.status is TaskStatus.COMPLETED
    assert task.output_json == {"recovered": True}
    assert task.execution_attempts == 2
    assert task.lease_owner is None and task.lease_expires_at is None
    assert event_count == outbox_count == 1


async def test_postgres_user_risk_lock_blocks_two_concurrent_yellow_commits(
    postgres_factory,
) -> None:
    factory = postgres_factory
    bus = EventBus()
    user_id = "postgres-risk-concurrency-user"
    bank = MockBankService(fixture_user_ids=frozenset({user_id}))
    provider = MockTransferProvider(factory, bank)
    registry = ToolRegistry()
    registry.register(build_list_accounts_tool(bank))
    registry.register(build_get_balance_tool(bank, provider.effective_balance))
    registry.register(build_search_payees_tool(bank))
    registry.register(build_commit_transfer_tool(factory, provider))
    registry.register(build_get_transfer_status_tool(factory, provider))
    engine = TransferWorkflowEngine(ToolExecutor(registry, PolicyService()))

    async def create_yellow_workflow():  # type: ignore[no-untyped-def]
        async with factory() as session:
            conversation = await ConversationService(session, bus).create(
                user_id=user_id, title="Concurrent risk gate"
            )
        async with factory() as session:
            accepted = await ConversationService(session, bus).accept_message(
                conversation_id=conversation.conversation_id,
                user_id=user_id,
                content="给张三转600",
            )
        async with factory() as session:
            workflow = await WorkflowService(session, bus, engine).create_transfer(
                user_id=user_id,
                conversation_id=conversation.conversation_id,
                source_task_id=accepted.task_id,
                intent=TransferIntent(recipient_query="张三", amount="600.00"),
            )
        async with factory() as session:
            workflow = await WorkflowService(session, bus, engine).select_payee(
                workflow.workflow_id,
                user_id=user_id,
                payee_id="payee_001",
                expected_version=workflow.version,
            )
        async with factory() as session:
            workflow = await WorkflowService(session, bus, engine).select_source_account(
                workflow.workflow_id,
                user_id=user_id,
                account_id="acc_salary",
                expected_version=workflow.version,
            )
        async with factory() as session:
            return await WorkflowService(session, bus, engine).approve(
                workflow.workflow_id,
                user_id=user_id,
                expected_version=workflow.version,
            )

    workflow_a = await create_yellow_workflow()
    workflow_b = await create_yellow_workflow()
    assert workflow_a.status is WorkflowStatus.READY_FOR_COMMIT
    assert workflow_b.status is WorkflowStatus.READY_FOR_COMMIT

    async def prepare(workflow):  # type: ignore[no-untyped-def]
        async with factory() as session:
            return await OperationService(session, bus, engine).prepare_transfer(
                workflow.workflow_id,
                user_id=user_id,
                expected_version=workflow.version,
            )

    results = await asyncio.gather(
        prepare(workflow_a), prepare(workflow_b), return_exceptions=True
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    rejected = next(result for result in results if isinstance(result, Exception))
    assert isinstance(rejected, OperationActionError)
    assert str(rejected) == "TRANSFER_RISK_REAUTH_REQUIRED"

    async with factory() as session:
        operation_count = await session.scalar(
            select(func.count())
            .select_from(OperationModel)
            .where(OperationModel.user_id == user_id)
        )
        workflows = list(
            (
                await session.execute(
                    select(WorkflowModel).where(WorkflowModel.user_id == user_id)
                )
            ).scalars()
        )
    assert operation_count == 1
    assert {workflow.status for workflow in workflows} == {
        WorkflowStatus.COMMITTING,
        WorkflowStatus.REAUTH_REQUIRED,
    }


async def test_concurrent_security_signals_do_not_lose_updates(postgres_factory) -> None:
    factory = postgres_factory
    user_id = "security-concurrency-user"
    workflow_id = uuid4()
    async with factory() as session:
        conversation = await ConversationRepository(session).create(
            user_id=user_id, title="Security concurrency"
        )
        task = await TaskRepository(session).create(
            conversation_id=conversation.conversation_id,
            user_id=user_id,
            task_type="USER_REQUEST",
            input_data={},
        )
        await session.commit()

    async def record_failure():
        async with factory() as session:
            status = await SecurityGuardService(session).record_reauthentication_result(
                user_id=user_id,
                workflow_id=workflow_id,
                conversation_id=conversation.conversation_id,
                task_id=task.task_id,
                succeeded=False,
            )
            await session.commit()
            return status

    await record_failure()
    await asyncio.gather(record_failure(), record_failure())

    async with factory() as session:
        state = await session.get(SecurityGuardStateModel, user_id)
        assert state is not None
        assert state.reauth_failure_count == 3
        assert (
            await SecurityGuardService(session).get_status(user_id)
        ).status is SecurityGuardStatus.WRITE_LOCKED


async def _create_postgres_red_transfer(factory, bus: EventBus, user_id: str):  # type: ignore[no-untyped-def]
    bank = MockBankService(fixture_user_ids=frozenset({user_id}))
    provider = MockTransferProvider(factory, bank)
    registry = ToolRegistry()
    registry.register(build_list_accounts_tool(bank))
    registry.register(build_get_balance_tool(bank, provider.effective_balance))
    registry.register(build_search_payees_tool(bank))
    registry.register(build_commit_transfer_tool(factory, provider))
    registry.register(build_get_transfer_status_tool(factory, provider))
    engine = TransferWorkflowEngine(ToolExecutor(registry, PolicyService()))
    reauth_provider = MockReauthenticationProvider("race-test-code")

    def workflows(session):  # type: ignore[no-untyped-def]
        return WorkflowService(
            session,
            bus,
            engine,
            reauth_provider=reauth_provider,
        )

    async with factory() as session:
        conversation = await ConversationService(session, bus).create(
            user_id=user_id, title="Security Operation race"
        )
    async with factory() as session:
        accepted = await ConversationService(session, bus).accept_message(
            conversation_id=conversation.conversation_id,
            user_id=user_id,
            content="给张三转2000",
        )
    async with factory() as session:
        workflow = await workflows(session).create_transfer(
            user_id=user_id,
            conversation_id=conversation.conversation_id,
            source_task_id=accepted.task_id,
            intent=TransferIntent(recipient_query="张三", amount=Decimal("2000.00")),
        )
    async with factory() as session:
        workflow = await workflows(session).select_payee(
            workflow.workflow_id,
            user_id=user_id,
            payee_id="payee_001",
            expected_version=workflow.version,
        )
    async with factory() as session:
        workflow = await workflows(session).select_source_account(
            workflow.workflow_id,
            user_id=user_id,
            account_id="acc_salary",
            expected_version=workflow.version,
        )
    async with factory() as session:
        workflow = await workflows(session).approve(
            workflow.workflow_id,
            user_id=user_id,
            expected_version=workflow.version,
        )
    assert workflow.status is WorkflowStatus.REAUTH_REQUIRED
    async with factory() as session:
        workflow = await workflows(session).start_reauthentication(
            workflow.workflow_id,
            user_id=user_id,
            expected_version=workflow.version,
        )
    async with factory() as session:
        workflow = await workflows(session).verify_reauthentication(
            workflow.workflow_id,
            user_id=user_id,
            reauth_id=workflow.reauth_summary.reauth_id,  # type: ignore[union-attr]
            verification_code="race-test-code",
            expected_version=workflow.version,
        )
    assert workflow.status is WorkflowStatus.READY_FOR_COMMIT
    return engine, provider, workflow


async def _create_postgres_subscription_cancel(factory, bus: EventBus, user_id: str):  # type: ignore[no-untyped-def]
    bank = MockBankService(fixture_user_ids=frozenset({user_id}))
    provider = MockSubscriptionProvider(factory, bank)
    registry = ToolRegistry()
    registry.register(build_subscription_analyze_tool(factory, bank))
    registry.register(build_subscription_cancel_tool(factory, provider))
    registry.register(build_subscription_status_tool(factory, provider))
    executor = ToolExecutor(registry, PolicyService())
    subscription_engine = SubscriptionCancellationWorkflow(executor)
    transfer_engine = TransferWorkflowEngine(executor)

    async with factory() as session:
        conversation = await ConversationService(session, bus).create(
            user_id=user_id, title="Security subscription race"
        )
    async with factory() as session:
        accepted = await ConversationService(session, bus).accept_message(
            conversation_id=conversation.conversation_id,
            user_id=user_id,
            content="取消星幕视频",
        )
    async with factory() as session:
        workflow = await WorkflowService(
            session,
            bus,
            transfer_engine,
            subscription_engine=subscription_engine,
        ).create_subscription_cancel(
            user_id=user_id,
            conversation_id=conversation.conversation_id,
            source_task_id=accepted.task_id,
            intent=SubscriptionCancelIntent(subscription_query="星幕视频"),
        )
    async with factory() as session:
        workflow = await WorkflowService(
            session,
            bus,
            transfer_engine,
            subscription_engine=subscription_engine,
        ).approve(
            workflow.workflow_id,
            user_id=user_id,
            expected_version=workflow.version,
        )
    assert workflow.status is WorkflowStatus.READY_FOR_COMMIT
    return transfer_engine, subscription_engine, provider, workflow


async def _seed_security_counter(
    factory,
    user_id: str,
    *,
    reauth_failures: int = 0,
    bypass_attempts: int = 0,
) -> None:  # type: ignore[no-untyped-def]
    async with factory() as session:
        state = await session.get(SecurityGuardStateModel, user_id)
        if state is None:
            state = SecurityGuardStateModel(user_id=user_id)
            session.add(state)
        now = datetime.now(UTC)
        state.reauth_failure_count = reauth_failures
        state.reauth_window_started_at = now if reauth_failures else None
        state.bypass_attempt_count = bypass_attempts
        state.bypass_window_started_at = now if bypass_attempts else None
        await session.commit()


async def test_security_lock_activation_wins_transfer_operation_race(
    postgres_factory,
) -> None:
    factory = postgres_factory
    bus = EventBus()
    user_id = "security-transfer-signal-wins"
    engine, provider, workflow = await _create_postgres_red_transfer(factory, bus, user_id)
    await _seed_security_counter(factory, user_id, reauth_failures=2)
    operation_attempted = asyncio.Event()

    async def prepare_transfer():  # type: ignore[no-untyped-def]
        async with factory() as session:
            service = OperationService(session, bus, engine)
            operation_attempted.set()
            return await service.prepare_transfer(
                workflow.workflow_id,
                user_id=user_id,
                expected_version=workflow.version,
            )

    async with factory() as signal_session:
        await acquire_security_user_lock(signal_session, user_id)
        locked = await SecurityGuardService(
            signal_session
        ).record_reauthentication_result(
            user_id=user_id,
            workflow_id=workflow.workflow_id,
            conversation_id=workflow.conversation_id,
            task_id=workflow.source_task_id,
            succeeded=False,
        )
        assert locked.status is SecurityGuardStatus.WRITE_LOCKED
        operation_task = asyncio.create_task(prepare_transfer())
        await operation_attempted.wait()
        await signal_session.commit()

    with pytest.raises(SecurityWriteLockedError):
        await operation_task
    async with factory() as session:
        operation_count = await session.scalar(
            select(func.count())
            .select_from(OperationModel)
            .where(OperationModel.workflow_id == workflow.workflow_id)
        )
        approval = (
            await session.execute(
                select(ApprovalModel).where(ApprovalModel.workflow_id == workflow.workflow_id)
            )
        ).scalar_one()
        persisted_workflow = await session.get(WorkflowModel, workflow.workflow_id)
    assert operation_count == 0
    assert approval.status is ApprovalStatus.APPROVED
    assert approval.consumed_at is None
    assert persisted_workflow is not None
    assert persisted_workflow.status is WorkflowStatus.READY_FOR_COMMIT
    assert await provider.transfer_count() == 0


async def test_transfer_operation_wins_then_security_lock_blocks_new_operation(
    postgres_factory,
) -> None:
    factory = postgres_factory
    bus = EventBus()
    user_id = "security-transfer-operation-wins"
    engine, provider, workflow = await _create_postgres_red_transfer(factory, bus, user_id)
    _, _, new_workflow = await _create_postgres_red_transfer(factory, bus, user_id)
    await _seed_security_counter(factory, user_id, reauth_failures=2)
    operation_has_lock = asyncio.Event()
    release_operation = asyncio.Event()
    signal_started = asyncio.Event()

    class PausingSecurityGuard(SecurityGuardService):
        async def require_write_allowed(self, checked_user_id: str, **context) -> None:
            await super().require_write_allowed(checked_user_id, **context)
            operation_has_lock.set()
            await release_operation.wait()

    async def prepare_transfer():  # type: ignore[no-untyped-def]
        async with factory() as session:
            service = OperationService(session, bus, engine)
            service.security_guard = PausingSecurityGuard(session)
            return await service.prepare_transfer(
                workflow.workflow_id,
                user_id=user_id,
                expected_version=workflow.version,
            )

    async def activate_lock():  # type: ignore[no-untyped-def]
        async with factory() as session:
            signal_started.set()
            status = await SecurityGuardService(session).record_reauthentication_result(
                user_id=user_id,
                workflow_id=workflow.workflow_id,
                conversation_id=workflow.conversation_id,
                task_id=workflow.source_task_id,
                succeeded=False,
            )
            await session.commit()
            return status

    operation_task = asyncio.create_task(prepare_transfer())
    await operation_has_lock.wait()
    signal_task = asyncio.create_task(activate_lock())
    await signal_started.wait()
    release_operation.set()
    operation, locked = await asyncio.gather(operation_task, signal_task)

    assert operation.status is OperationStatus.CREATED
    assert locked.status is SecurityGuardStatus.WRITE_LOCKED
    async with factory() as session:
        retry = await OperationService(session, bus, engine).prepare_transfer(
            workflow.workflow_id, user_id=user_id, expected_version=workflow.version
        )
        assert retry.operation_id == operation.operation_id
    async with factory() as session:
        with pytest.raises(SecurityWriteLockedError):
            await OperationService(session, bus, engine).prepare_transfer(
                new_workflow.workflow_id,
                user_id=user_id,
                expected_version=new_workflow.version,
            )
    async with factory() as session:
        operation_count = await session.scalar(
            select(func.count())
            .select_from(OperationModel)
            .where(OperationModel.workflow_id == workflow.workflow_id)
        )
    assert operation_count == 1
    assert await provider.transfer_count() == 0


async def test_bypass_lock_activation_wins_subscription_operation_race(
    postgres_factory,
) -> None:
    factory = postgres_factory
    bus = EventBus()
    user_id = "security-subscription-signal-wins"
    transfer_engine, subscription_engine, provider, workflow = (
        await _create_postgres_subscription_cancel(factory, bus, user_id)
    )
    await _seed_security_counter(factory, user_id, bypass_attempts=4)
    operation_attempted = asyncio.Event()

    async def prepare_subscription():  # type: ignore[no-untyped-def]
        async with factory() as session:
            service = OperationService(
                session,
                bus,
                transfer_engine,
                subscription_engine=subscription_engine,
            )
            operation_attempted.set()
            return await service.prepare_subscription_cancel(
                workflow.workflow_id,
                user_id=user_id,
                expected_version=workflow.version,
            )

    async with factory() as signal_session:
        await acquire_security_user_lock(signal_session, user_id)
        locked = await SecurityGuardService(
            signal_session
        ).record_control_bypass_attempt(
            user_id=user_id,
            workflow_id=workflow.workflow_id,
            conversation_id=workflow.conversation_id,
            task_id=workflow.source_task_id,
        )
        assert locked.status is SecurityGuardStatus.WRITE_LOCKED
        operation_task = asyncio.create_task(prepare_subscription())
        await operation_attempted.wait()
        await signal_session.commit()

    with pytest.raises(SecurityWriteLockedError):
        await operation_task
    async with factory() as session:
        operation_count = await session.scalar(
            select(func.count())
            .select_from(OperationModel)
            .where(OperationModel.workflow_id == workflow.workflow_id)
        )
        approval = (
            await session.execute(
                select(ApprovalModel).where(ApprovalModel.workflow_id == workflow.workflow_id)
            )
        ).scalar_one()
        persisted_workflow = await session.get(WorkflowModel, workflow.workflow_id)
    assert operation_count == 0
    assert approval.status is ApprovalStatus.APPROVED
    assert approval.consumed_at is None
    assert persisted_workflow is not None
    assert persisted_workflow.status is WorkflowStatus.READY_FOR_COMMIT
    assert await provider.cancellation_count() == 0
