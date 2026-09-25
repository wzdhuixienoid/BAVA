"""Opt-in real-DeepSeek smoke for transfer approval and step-up authentication."""

import asyncio
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from banking_api.application.conversation_service import ConversationService
from banking_api.application.workflow_service import WorkflowService
from banking_api.config.settings import Settings
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
    build_get_balance_tool,
    build_list_accounts_tool,
    build_search_payees_tool,
)
from banking_api.tools.executor import ToolExecutor
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
    provider = OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    prompt = "给张三转2000"
    decision = await RequestRouter(provider).route(prompt)
    if decision.route is not RequestRoute.TRANSFER_WORKFLOW:
        raise AssertionError(f"unexpected route: {decision.route.value}")
    intent = await TransferIntentExtractor(provider).extract(prompt)
    if intent.recipient_query != "张三" or str(intent.amount) not in {"2000", "2000.00"}:
        raise AssertionError("intent extraction did not preserve recipient and amount")

    bank = MockBankService()
    balances_before = {
        item["account_id"]: bank.get_balance(item["account_id"])["balance"]
        for item in bank.list_accounts()
    }
    transactions_before = bank.list_transactions()
    registry = ToolRegistry()
    registry.register(build_list_accounts_tool(bank))
    registry.register(build_get_balance_tool(bank))
    registry.register(build_search_payees_tool(bank))
    engine = TransferWorkflowEngine(ToolExecutor(registry, PolicyService()))
    database = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(database, expire_on_commit=False)
    async with database.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    bus = EventBus()
    reauth_provider = MockReauthenticationProvider(settings.mock_reauth_code)

    async with factory() as session:
        conversation = await ConversationService(session, bus).create(
            user_id="smoke-transfer-user", title="Transfer authorization smoke"
        )
    async with factory() as session:
        accepted = await ConversationService(session, bus).accept_message(
            conversation_id=conversation.conversation_id,
            user_id="smoke-transfer-user",
            content=prompt,
        )
    async with factory() as session:
        workflow = await WorkflowService(
            session, bus, engine, reauth_provider=reauth_provider
        ).create_transfer(
            user_id="smoke-transfer-user",
            conversation_id=conversation.conversation_id,
            source_task_id=accepted.task_id,
            intent=intent,
        )
    if workflow.state["required_input"]["type"] != "PAYEE_SELECTION":
        raise AssertionError("expected payee selection")
    if len(workflow.state["required_input"]["options"]) != 2:
        raise AssertionError("expected exactly two deterministic 张三 candidates")

    async with factory() as session:
        workflow = await WorkflowService(
            session, bus, engine, reauth_provider=reauth_provider
        ).select_payee(
            workflow.workflow_id,
            user_id="smoke-transfer-user",
            payee_id="payee_001",
            expected_version=workflow.version,
        )
    async with factory() as session:
        workflow = await WorkflowService(
            session, bus, engine, reauth_provider=reauth_provider
        ).select_source_account(
            workflow.workflow_id,
            user_id="smoke-transfer-user",
            account_id="acc_salary",
            expected_version=workflow.version,
        )
    async with factory() as session:
        workflow = await WorkflowService(
            session, bus, engine, reauth_provider=reauth_provider
        ).approve(
            workflow.workflow_id,
            user_id="smoke-transfer-user",
            expected_version=workflow.version,
        )
    async with factory() as session:
        workflow = await WorkflowService(
            session, bus, engine, reauth_provider=reauth_provider
        ).start_reauthentication(
            workflow.workflow_id,
            user_id="smoke-transfer-user",
            expected_version=workflow.version,
        )
    if workflow.reauth_summary is None:
        raise AssertionError("reauthentication challenge was not created")
    async with factory() as session:
        workflow = await WorkflowService(
            session, bus, engine, reauth_provider=reauth_provider
        ).verify_reauthentication(
            workflow.workflow_id,
            user_id="smoke-transfer-user",
            reauth_id=workflow.reauth_summary.reauth_id,
            verification_code=settings.mock_reauth_code,
            expected_version=workflow.version,
        )

    balances_after = {
        item["account_id"]: bank.get_balance(item["account_id"])["balance"]
        for item in bank.list_accounts()
    }
    if balances_before != balances_after or transactions_before != bank.list_transactions():
        raise AssertionError("authorization workflow mutated synthetic bank data")
    capabilities = {spec.capability_id for spec in registry.all()}
    if capabilities != {"account.list", "account.get_balance", "payee.search"}:
        raise AssertionError("unexpected capability registered")
    if workflow.status.value != "READY_FOR_COMMIT":
        raise AssertionError(f"unexpected final status: {workflow.status.value}")
    if workflow.approval_summary is None or workflow.approval_summary.status.value != "APPROVED":
        raise AssertionError("approval was not persisted")
    if workflow.reauth_summary is None or workflow.reauth_summary.status.value != "VERIFIED":
        raise AssertionError("reauthentication was not verified")

    print(
        "smoke.result",
        {
            "route": decision.route.value,
            "recipient": intent.recipient_query,
            "payee_candidates": 2,
            "source_account": "acc_salary",
            "status": workflow.status.value,
            "approval": workflow.approval_summary.status.value,
            "reauth": workflow.reauth_summary.status.value,
            "write_calls": 0,
            "balance_unchanged": True,
            "transactions_unchanged": True,
        },
    )
    await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
