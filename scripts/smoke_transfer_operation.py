"""Opt-in real-DeepSeek smoke for the idempotent transfer operation slice."""

import asyncio
from decimal import Decimal
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from banking_api.application.conversation_service import ConversationService
from banking_api.application.operation_service import OperationService
from banking_api.application.workflow_service import WorkflowService
from banking_api.config.settings import Settings
from banking_api.domain.enums import ApprovalStatus, OperationStatus, WorkflowStatus
from banking_api.llm.openai_compatible_provider import OpenAICompatibleProvider
from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.database import Base
from banking_api.policy.service import PolicyService
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.routing.models import RequestRoute
from banking_api.routing.request_router import RequestRouter
from banking_api.runtime.event_bus import EventBus
from banking_api.security.reauthentication.mock_provider import (
    MockReauthenticationProvider,
)
from banking_api.tools.banking import (
    build_commit_transfer_tool,
    build_get_balance_tool,
    build_get_transfer_status_tool,
    build_list_accounts_tool,
    build_search_payees_tool,
)
from banking_api.tools.executor import ToolExecutor
from banking_api.transfers.mock_provider import MockTransferProvider
from banking_api.workflows.transfer.engine import TransferWorkflowEngine
from banking_api.workflows.transfer.intent_extractor import TransferIntentExtractor


async def main() -> None:
    settings = Settings()
    if not settings.llm_base_url or not settings.llm_api_key or not settings.llm_model:
        raise SystemExit("LLM_BASE_URL, LLM_API_KEY and LLM_MODEL are required")
    print(
        "provider.config",
        {
            "provider": settings.llm_provider,
            "base_url_domain": urlparse(settings.llm_base_url).netloc,
            "model": settings.llm_model,
        },
    )
    llm = OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    prompt = "给张三转2000"
    decision = await RequestRouter(llm).route(prompt)
    intent = await TransferIntentExtractor(llm).extract(prompt)
    if decision.route is not RequestRoute.TRANSFER_WORKFLOW:
        raise AssertionError(f"unexpected route: {decision.route.value}")
    if intent.recipient_query != "张三" or intent.amount != Decimal("2000"):
        raise AssertionError("intent extraction did not preserve recipient and amount")

    database = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(database, expire_on_commit=False)
    async with database.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    user_id = "smoke-transfer-operation-user"
    bank = MockBankService(fixture_user_ids=frozenset({user_id}))
    transfer_provider = MockTransferProvider(factory, bank)
    registry = ToolRegistry()
    registry.register(build_list_accounts_tool(bank))
    registry.register(build_get_balance_tool(bank, transfer_provider.effective_balance))
    registry.register(build_search_payees_tool(bank))
    registry.register(build_commit_transfer_tool(factory, transfer_provider))
    registry.register(build_get_transfer_status_tool(factory, transfer_provider))
    engine = TransferWorkflowEngine(ToolExecutor(registry, PolicyService()))
    reauth_provider = MockReauthenticationProvider(settings.mock_reauth_code)
    bus = EventBus()
    transactions_before = bank.list_transactions(user_id=user_id)
    balance_before = await transfer_provider.effective_balance(user_id, "acc_salary")

    async with factory() as session:
        conversation = await ConversationService(session, bus).create(
            user_id=user_id, title="Transfer operation smoke"
        )
    async with factory() as session:
        accepted = await ConversationService(session, bus).accept_message(
            conversation_id=conversation.conversation_id,
            user_id=user_id,
            content=prompt,
        )

    def workflow_service(session):  # type: ignore[no-untyped-def]
        return WorkflowService(session, bus, engine, reauth_provider=reauth_provider)

    async with factory() as session:
        workflow = await workflow_service(session).create_transfer(
            user_id=user_id,
            conversation_id=conversation.conversation_id,
            source_task_id=accepted.task_id,
            intent=intent,
        )
    if len(workflow.state["required_input"]["options"]) != 2:
        raise AssertionError("expected exactly two deterministic 张三 candidates")
    async with factory() as session:
        workflow = await workflow_service(session).select_payee(
            workflow.workflow_id,
            user_id=user_id,
            payee_id="payee_001",
            expected_version=workflow.version,
        )
    async with factory() as session:
        workflow = await workflow_service(session).select_source_account(
            workflow.workflow_id,
            user_id=user_id,
            account_id="acc_salary",
            expected_version=workflow.version,
        )
    async with factory() as session:
        workflow = await workflow_service(session).approve(
            workflow.workflow_id,
            user_id=user_id,
            expected_version=workflow.version,
        )
    async with factory() as session:
        workflow = await workflow_service(session).start_reauthentication(
            workflow.workflow_id,
            user_id=user_id,
            expected_version=workflow.version,
        )
    async with factory() as session:
        workflow = await workflow_service(session).verify_reauthentication(
            workflow.workflow_id,
            user_id=user_id,
            reauth_id=workflow.reauth_summary.reauth_id,  # type: ignore[union-attr]
            verification_code=settings.mock_reauth_code,
            expected_version=workflow.version,
        )
    async with factory() as session:
        operation = await OperationService(session, bus, engine).commit_workflow(
            workflow.workflow_id,
            user_id=user_id,
            expected_version=workflow.version,
        )
    async with factory() as session:
        final_workflow = await workflow_service(session).get(workflow.workflow_id, user_id=user_id)

    balance_after = await transfer_provider.effective_balance(user_id, "acc_salary")
    if final_workflow.status is not WorkflowStatus.SUCCEEDED:
        raise AssertionError(f"unexpected workflow status: {final_workflow.status.value}")
    if operation.status is not OperationStatus.SUCCEEDED:
        raise AssertionError(f"unexpected operation status: {operation.status.value}")
    if final_workflow.approval_summary.status is not ApprovalStatus.CONSUMED:  # type: ignore[union-attr]
        raise AssertionError("approval was not consumed")
    if balance_after - balance_before != Decimal("-2000.00"):
        raise AssertionError("effective balance did not decrease exactly once")
    if await transfer_provider.transfer_count() != 1:
        raise AssertionError("provider idempotency ledger count is not one")
    if bank.list_transactions(user_id=user_id) != transactions_before:
        raise AssertionError("committed synthetic transaction fixture was mutated")

    print(
        "smoke.result",
        {
            "route": decision.route.value,
            "recipient": intent.recipient_query,
            "payee_candidates": 2,
            "source_account": "acc_salary",
            "workflow": final_workflow.status.value,
            "operation": operation.status.value,
            "approval": final_workflow.approval_summary.status.value,  # type: ignore[union-attr]
            "balance_delta": str(balance_after - balance_before),
            "provider_transfer_count": await transfer_provider.transfer_count(),
        },
    )
    await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
