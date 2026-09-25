from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from banking_api.domain.enums import PolicyDecision, WorkflowStatus
from banking_api.tools.executor import ToolExecutor
from banking_api.workflows.transfer.models import (
    TransferDraft,
    TransferIntent,
    TransferRequiredInput,
    TransferRequiredInputType,
    TransferReviewPayload,
    TransferValidationIssue,
    TransferValidationResult,
    TransferWorkflowState,
)
from banking_api.workflows.transfer.validation import amount_is_valid, normalize_hint

TRANSFER_CALLER = "workflow:transfer"
TRANSFER_CAPABILITIES = frozenset(
    {
        "payee.search",
        "account.list",
        "account.get_balance",
        "transfer.commit",
        "transfer.get_status",
    }
)
ELIGIBLE_ACCOUNT_TYPES = frozenset({"DEBIT", "SAVINGS"})


class TransferWorkflowEngineError(Exception):
    pass


class InvalidWorkflowActionError(Exception):
    pass


class TransferWorkflowEngine:
    """Deterministic transfer resolver and Tool/Policy execution boundary."""

    def __init__(self, executor: ToolExecutor) -> None:
        self._executor = executor

    async def start(
        self, intent: TransferIntent
    ) -> tuple[WorkflowStatus, TransferWorkflowState]:
        draft = TransferDraft(**intent.model_dump())
        return await self.advance(TransferWorkflowState(draft=draft))

    async def advance(
        self, state: TransferWorkflowState
    ) -> tuple[WorkflowStatus, TransferWorkflowState]:
        state.required_input = None
        state.validation = None
        state.review_payload = None
        draft = state.draft

        if not draft.recipient_query:
            return self._waiting(
                state,
                TransferRequiredInputType.RECIPIENT_QUERY,
                "请提供收款人姓名或手机别名。",
            )

        payees = await self._search_payees(draft.recipient_query)
        state.payee_options = payees
        if not payees:
            return self._failed(state, "PAYEE_NOT_FOUND", "未找到匹配的收款人。")
        selected_payee = next(
            (item for item in payees if item["payee_id"] == draft.payee_id), None
        )
        if draft.payee_id and selected_payee is None:
            return self._failed(state, "PAYEE_NOT_FOUND", "所选收款人不再可用。")
        if draft.payee_id is None:
            if len(payees) == 1:
                selected_payee = payees[0]
                draft.payee_id = selected_payee["payee_id"]
            else:
                state.required_input = TransferRequiredInput(
                    type=TransferRequiredInputType.PAYEE_SELECTION,
                    options=payees,
                    message="找到多个同名收款人，请选择具体收款人。",
                )
                return WorkflowStatus.WAITING_FOR_INPUT, state

        if draft.amount is None:
            return self._waiting(
                state,
                TransferRequiredInputType.AMOUNT,
                "请输入转账金额。",
            )
        if not amount_is_valid(draft.amount):
            return self._failed(
                state, "INVALID_TRANSFER_AMOUNT", "转账金额必须大于 0 且最多两位小数。"
            )

        accounts = await self._list_accounts()
        selected_account = next(
            (item for item in accounts if item["account_id"] == draft.source_account_id),
            None,
        )
        if draft.source_account_id and selected_account is None:
            return self._failed(state, "SOURCE_ACCOUNT_NOT_FOUND", "所选账户不存在。")
        if selected_account is not None and not self._eligible(selected_account):
            return self._failed(
                state,
                "SOURCE_ACCOUNT_NOT_ELIGIBLE",
                "该账户不能作为本次转账的付款账户。",
            )

        eligible = [item for item in accounts if self._eligible(item)]
        source_options = []
        for account in eligible[:10]:
            option_balance = await self._get_balance(account["account_id"])
            source_options.append(
                {**account, "available_balance": option_balance["balance"]}
            )
        state.source_account_options = source_options
        if selected_account is None and draft.source_account_hint:
            normalized = normalize_hint(draft.source_account_hint)
            matches = [
                item
                for item in eligible
                if normalize_hint(item["display_name"]) == normalized
                or normalize_hint(item["masked_number"]) == normalized
            ]
            if len(matches) == 1:
                selected_account = matches[0]
                draft.source_account_id = selected_account["account_id"]

        if selected_account is None:
            state.required_input = TransferRequiredInput(
                type=TransferRequiredInputType.SOURCE_ACCOUNT_SELECTION,
                options=source_options,
                message="请选择付款账户。",
            )
            return WorkflowStatus.WAITING_FOR_INPUT, state

        source_currency = selected_account["currency"]
        if draft.currency is None:
            draft.currency = source_currency
        elif draft.currency.upper() != source_currency.upper():
            return self._failed(
                state,
                "CURRENCY_MISMATCH",
                "本轮不支持换汇，转账币种必须与付款账户一致。",
            )
        else:
            draft.currency = draft.currency.upper()

        balance = await self._get_balance(selected_account["account_id"])
        available = Decimal(str(balance["balance"]))
        if available < draft.amount:
            return self._failed(
                state,
                "INSUFFICIENT_FUNDS",
                "付款账户可用余额不足。",
                available_balance=available,
            )

        assert selected_payee is not None
        state.validation = TransferValidationResult(
            is_valid=True,
            validated_at=datetime.now(UTC),
            available_balance=available,
            issues=[],
        )
        state.review_payload = TransferReviewPayload(
            source_account_id=selected_account["account_id"],
            source_account_display_name=selected_account["display_name"],
            source_account_masked_number=selected_account["masked_number"],
            payee_id=selected_payee["payee_id"],
            payee_display_name=selected_payee["display_name"],
            payee_bank_name=selected_payee["bank_name"],
            payee_masked_account=selected_payee["masked_account"],
            amount=draft.amount,
            currency=draft.currency,
        )
        return WorkflowStatus.READY_FOR_REVIEW, state

    async def validate_payee_action(
        self,
        state: TransferWorkflowState,
        payee_id: str,
        *,
        allow_outside_selection: bool = False,
    ) -> None:
        required = state.required_input
        if not allow_outside_selection:
            if required is None or required.type is not TransferRequiredInputType.PAYEE_SELECTION:
                raise InvalidWorkflowActionError("Workflow is not waiting for payee selection")
            candidates = required.options
        else:
            if not state.draft.recipient_query:
                raise InvalidWorkflowActionError("Recipient query is missing")
            candidates = await self._search_payees(state.draft.recipient_query)
        if payee_id not in {str(item.get("payee_id")) for item in candidates}:
            raise InvalidWorkflowActionError("Payee is not one of the authoritative options")

    async def validate_account_action(
        self,
        state: TransferWorkflowState,
        account_id: str,
        *,
        allow_outside_selection: bool = False,
    ) -> None:
        required = state.required_input
        if not allow_outside_selection and (
            required is None
            or required.type is not TransferRequiredInputType.SOURCE_ACCOUNT_SELECTION
        ):
            raise InvalidWorkflowActionError("Workflow is not waiting for account selection")
        accounts = await self._list_accounts()
        if account_id not in {str(item["account_id"]) for item in accounts}:
            raise InvalidWorkflowActionError("Account does not exist")

    def ensure_commit_allowed(self) -> None:
        spec = self._executor.registry.get("transfer.commit")
        decision = self._executor.policy.evaluate(
            spec=spec,
            caller=TRANSFER_CALLER,
            authenticated=True,
            agent_allowlist=TRANSFER_CAPABILITIES,
        )
        if decision.decision is not PolicyDecision.ALLOW:
            raise TransferWorkflowEngineError("TRANSFER_COMMIT_POLICY_DENIED")

    async def submit_operation(self, operation_id: UUID) -> dict[str, Any]:
        return await self._execute_operation_tool("commit_transfer", operation_id)

    async def query_operation_status(self, operation_id: UUID) -> dict[str, Any]:
        return await self._execute_operation_tool("get_transfer_status", operation_id)

    async def _execute_operation_tool(
        self, tool_name: str, operation_id: UUID
    ) -> dict[str, Any]:
        result = await self._executor.execute(
            tool_name=tool_name,
            arguments={"operation_id": str(operation_id)},
            caller=TRANSFER_CALLER,
            authenticated=True,
            agent_allowlist=TRANSFER_CAPABILITIES,
        )
        if not result.ok or result.output is None:
            code = result.error.code.value if result.error is not None else "UNKNOWN"
            raise TransferWorkflowEngineError(f"Operation capability failed: {code}")
        return result.output

    async def _search_payees(self, query: str) -> list[dict[str, Any]]:
        output = await self._read("search_payees", {"query": query})
        return list(output["payees"])

    async def _list_accounts(self) -> list[dict[str, Any]]:
        output = await self._read("list_accounts", {})
        return list(output["accounts"])

    async def _get_balance(self, account_id: str) -> dict[str, Any]:
        return await self._read("get_balance", {"account_id": account_id})

    async def _read(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._executor.execute(
            tool_name=tool_name,
            arguments=arguments,
            caller=TRANSFER_CALLER,
            authenticated=True,
            agent_allowlist=TRANSFER_CAPABILITIES,
        )
        if not result.ok or result.output is None:
            code = result.error.code.value if result.error is not None else "UNKNOWN"
            raise TransferWorkflowEngineError(f"Read capability failed: {code}")
        return result.output

    @staticmethod
    def _eligible(account: dict[str, Any]) -> bool:
        return (
            account["account_type"] in ELIGIBLE_ACCOUNT_TYPES
            and account["status"] == "ACTIVE"
        )

    @staticmethod
    def _waiting(
        state: TransferWorkflowState,
        required_type: TransferRequiredInputType,
        message: str,
    ) -> tuple[WorkflowStatus, TransferWorkflowState]:
        state.required_input = TransferRequiredInput(
            type=required_type, options=[], message=message
        )
        return WorkflowStatus.WAITING_FOR_INPUT, state

    @staticmethod
    def _failed(
        state: TransferWorkflowState,
        code: str,
        message: str,
        available_balance: Decimal | None = None,
    ) -> tuple[WorkflowStatus, TransferWorkflowState]:
        state.validation = TransferValidationResult(
            is_valid=False,
            validated_at=datetime.now(UTC),
            available_balance=available_balance,
            issues=[TransferValidationIssue(code=code, message=message)],
        )
        return WorkflowStatus.FAILED, state
