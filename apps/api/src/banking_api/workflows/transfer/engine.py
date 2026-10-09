from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from banking_api.domain.enums import PolicyDecision, WorkflowStatus
from banking_api.domain.principal import ExecutionPrincipal
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
from banking_api.workflows.transfer.risk import (
    TransferRiskCurrencyUnsupportedError,
    TransferRiskPolicy,
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
        self.aa_resolver = None
        self.time_extractor = None

    async def start(
        self, intent: TransferIntent, *, principal: ExecutionPrincipal
    ) -> tuple[WorkflowStatus, TransferWorkflowState]:
        draft = TransferDraft(**intent.model_dump(exclude={"execution_time_text", "time_intent"}))
        if intent.execution_time_text is not None:
            await self.resolve_time(
                draft,
                intent.execution_time_text,
                received_at=datetime.now(UTC),
                intent=intent.time_intent,
            )
        return await self.advance(TransferWorkflowState(draft=draft), principal=principal)

    async def advance(
        self, state: TransferWorkflowState, *, principal: ExecutionPrincipal, session=None
    ) -> tuple[WorkflowStatus, TransferWorkflowState]:
        state.required_input = None
        state.validation = None
        state.review_payload = None
        draft = state.draft
        if draft.schedule_requested and draft.scheduled_for is None:
            return self._waiting(
                state,
                TransferRequiredInputType.EXECUTION_TIME,
                (
                    "周期转账需明确每月日期、执行时刻和总次数（2 至 12 次，最长 366 天）。"
                    if draft.recurrence_text
                    else "执行时间已过去或未满足最小提前量。"
                    if draft.schedule_time_error == "SCHEDULE_TIME_TOO_SOON"
                    else "执行时间超出允许的预约期限。"
                    if draft.schedule_time_error == "SCHEDULE_TIME_TOO_FAR"
                    else "时间表达无法唯一确定。"
                )
                + (
                    "例如每月1号上午9点，共3次。"
                    if draft.recurrence_text
                    else "请提供明确日期和时间，例如明天早上9点或2026-10-09 09:00。"
                ),
            )

        if not draft.recipient_query and not draft.aa_share_id:
            return self._waiting(
                state,
                TransferRequiredInputType.RECIPIENT_QUERY,
                "请提供收款人姓名或别名。",
            )

        aa_target = None
        if draft.aa_share_id:
            if self.aa_resolver is None:
                return self._failed(state, "AA_UNAVAILABLE", "AA 收款服务不可用。")
            aa_target = await self.aa_resolver(
                share_id=draft.aa_share_id, user_id=principal.user_id
            )
            if aa_target is None:
                return self._failed(
                    state, "AA_SHARE_NOT_PAYABLE", "AA 份额已取消、过期或不属于当前身份。"
                )
            if (
                draft.amount != Decimal(aa_target["amount"])
                or draft.remark != aa_target["remark"]
                or draft.currency != "CNY"
            ):
                return self._failed(
                    state, "AA_SNAPSHOT_IMMUTABLE", "AA 收款金额、备注与目标不能修改。"
                )
            payees = [aa_target["payee"]]
        else:
            payees = await self._search_payees(draft.recipient_query, principal=principal)
        state.payee_options = payees
        if not payees:
            return self._waiting(
                state,
                TransferRequiredInputType.RECIPIENT_QUERY,
                "未找到匹配的收款人，请选择已有收款人或新增收款人。",
            )
        selected_payee = next((item for item in payees if item["payee_id"] == draft.payee_id), None)
        if draft.payee_id and selected_payee is None:
            return self._failed(state, "PAYEE_NOT_FOUND", "所选收款人不再可用。")
        if draft.payee_id is None:
            query = "".join((draft.recipient_query or "").casefold().split())
            exact = len(payees) == 1 and query in {
                "".join(str(payees[0].get(key, "")).casefold().split())
                for key in ("display_name", "phone_alias")
            }
            if len(payees) == 1 and (exact or draft.aa_share_id):
                selected_payee = payees[0]
                draft.payee_id = selected_payee["payee_id"]
            else:
                state.required_input = TransferRequiredInput(
                    type=TransferRequiredInputType.PAYEE_SELECTION,
                    options=payees,
                    message="找到可能匹配的收款人，请核对并选择具体收款人。",
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

        accounts = await self._list_accounts(principal=principal)
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
            option_balance = await self._get_balance(account["account_id"], principal=principal)
            source_options.append({**account, "available_balance": option_balance["balance"]})
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

        try:
            TransferRiskPolicy.require_supported_currency(draft.currency)
        except TransferRiskCurrencyUnsupportedError as exc:
            state.risk_decision = None
            return self._failed(state, exc.code, exc.message)

        balance = await self._get_balance(selected_account["account_id"], principal=principal)
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
        target_version = None
        if draft.schedule_requested:
            import hashlib
            import json

            from sqlalchemy import or_, select

            from banking_api.persistence.models import PayeeModel

            identity = {
                key: selected_payee[key] for key in ("payee_id", "bank_name", "masked_account")
            }
            identity["account_fingerprint"] = None
            if session is not None:
                registered = await session.scalar(
                    select(PayeeModel).where(
                        PayeeModel.user_id == principal.user_id,
                        or_(
                            PayeeModel.payee_id == draft.payee_id,
                            PayeeModel.source_payee_id == draft.payee_id,
                        ),
                    )
                )
                identity["account_fingerprint"] = (
                    registered.account_fingerprint if registered else None
                )
            target_version = hashlib.sha256(
                json.dumps(identity, sort_keys=True).encode()
            ).hexdigest()
        state.review_payload = TransferReviewPayload(
            recurrence=draft.recurrence,
            payee_target_version=target_version,
            source_account_id=selected_account["account_id"],
            source_account_display_name=selected_account["display_name"],
            source_account_masked_number=selected_account["masked_number"],
            payee_id=selected_payee["payee_id"],
            payee_display_name=selected_payee["display_name"],
            payee_bank_name=selected_payee["bank_name"],
            payee_masked_account=selected_payee["masked_account"],
            amount=draft.amount,
            currency=draft.currency,
            aa_share_id=draft.aa_share_id,
            aa_request_id=aa_target["request_id"] if aa_target else None,
            destination_user_id=aa_target["destination_user_id"] if aa_target else None,
            destination_account_id=aa_target["destination_account_id"] if aa_target else None,
            remark=draft.remark,
            scheduled_for=draft.scheduled_for,
            execute_deadline=draft.execute_deadline,
            business_timezone=draft.business_timezone,
        )
        return WorkflowStatus.READY_FOR_REVIEW, state

    async def validate_payee_action(
        self,
        state: TransferWorkflowState,
        payee_id: str,
        *,
        principal: ExecutionPrincipal,
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
            candidates = await self._search_payees(state.draft.recipient_query, principal=principal)
        if payee_id not in {str(item.get("payee_id")) for item in candidates}:
            raise InvalidWorkflowActionError("Payee is not one of the authoritative options")

    async def validate_account_action(
        self,
        state: TransferWorkflowState,
        account_id: str,
        *,
        principal: ExecutionPrincipal,
        allow_outside_selection: bool = False,
    ) -> None:
        required = state.required_input
        if not allow_outside_selection and (
            required is None
            or required.type is not TransferRequiredInputType.SOURCE_ACCOUNT_SELECTION
        ):
            raise InvalidWorkflowActionError("Workflow is not waiting for account selection")
        accounts = await self._list_accounts(principal=principal)
        if account_id not in {str(item["account_id"]) for item in accounts}:
            raise InvalidWorkflowActionError("Account does not exist")

    async def resolve_time(
        self, draft: TransferDraft, value: str, *, received_at: datetime, intent=None
    ):
        if self.time_extractor is None and intent is None:
            # Legacy programmatic clients/tests only. The app always binds the LLM extractor.
            self.set_time(draft, value, received_at=received_at)
            return
        from banking_api.config.settings import get_settings
        from banking_api.workflows.transfer.time_intent import resolve_time_intent

        draft.schedule_requested = True
        draft.business_timezone = get_settings().banking_business_timezone
        draft.schedule_time_error = None
        draft.recurrence = None
        draft.recurrence_text = None
        try:
            if intent is None:
                intent = await self.time_extractor.extract(value)
            if intent.kind == "MONTHLY":
                draft.recurrence_text = value
            draft.scheduled_for, draft.execute_deadline, draft.recurrence = resolve_time_intent(
                intent, received_at
            )
        except (ValueError, OverflowError) as exc:
            draft.schedule_time_error = str(exc)
            draft.scheduled_for = draft.execute_deadline = None

    @staticmethod
    def set_time(draft: TransferDraft, value: str, *, received_at: datetime) -> None:
        from banking_api.config.settings import get_settings
        from banking_api.transfers.schedule_time import (
            is_monthly_expression,
            parse_execution_time,
            parse_monthly_recurrence,
        )

        draft.schedule_requested = True
        draft.schedule_time_error = None
        draft.recurrence = None
        draft.recurrence_text = value if is_monthly_expression(value) else None
        draft.business_timezone = get_settings().banking_business_timezone
        try:
            if draft.recurrence_text:
                from datetime import timedelta

                draft.recurrence = parse_monthly_recurrence(value, received_at)
                draft.scheduled_for = draft.recurrence.occurrences[0]
                draft.execute_deadline = draft.scheduled_for + timedelta(
                    seconds=get_settings().scheduled_transfer_late_window_seconds
                )
            else:
                draft.scheduled_for, draft.execute_deadline = parse_execution_time(
                    value, received_at
                )
        except (ValueError, OverflowError) as exc:
            draft.schedule_time_error = str(exc)
            draft.scheduled_for = draft.execute_deadline = None

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

    async def submit_operation(
        self, operation_id: UUID, *, principal: ExecutionPrincipal
    ) -> dict[str, Any]:
        return await self._execute_operation_tool(
            "commit_transfer", operation_id, principal=principal
        )

    async def query_operation_status(
        self, operation_id: UUID, *, principal: ExecutionPrincipal
    ) -> dict[str, Any]:
        return await self._execute_operation_tool(
            "get_transfer_status", operation_id, principal=principal
        )

    async def _execute_operation_tool(
        self,
        tool_name: str,
        operation_id: UUID,
        *,
        principal: ExecutionPrincipal,
    ) -> dict[str, Any]:
        result = await self._executor.execute(
            tool_name=tool_name,
            arguments={"operation_id": str(operation_id)},
            caller=TRANSFER_CALLER,
            principal=principal,
            agent_allowlist=TRANSFER_CAPABILITIES,
        )
        if not result.ok or result.output is None:
            code = result.error.code.value if result.error is not None else "UNKNOWN"
            raise TransferWorkflowEngineError(f"Operation capability failed: {code}")
        return result.output

    async def _search_payees(
        self, query: str, *, principal: ExecutionPrincipal
    ) -> list[dict[str, Any]]:
        output = await self._read("search_payees", {"query": query}, principal=principal)
        return list(output["payees"])

    async def _list_accounts(self, *, principal: ExecutionPrincipal) -> list[dict[str, Any]]:
        output = await self._read("list_accounts", {}, principal=principal)
        return list(output["accounts"])

    async def _get_balance(
        self, account_id: str, *, principal: ExecutionPrincipal
    ) -> dict[str, Any]:
        return await self._read("get_balance", {"account_id": account_id}, principal=principal)

    async def _read(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        principal: ExecutionPrincipal,
    ) -> dict[str, Any]:
        result = await self._executor.execute(
            tool_name=tool_name,
            arguments=arguments,
            caller=TRANSFER_CALLER,
            principal=principal,
            agent_allowlist=TRANSFER_CAPABILITIES,
        )
        if not result.ok or result.output is None:
            code = result.error.code.value if result.error is not None else "UNKNOWN"
            raise TransferWorkflowEngineError(f"Read capability failed: {code}")
        return result.output

    @staticmethod
    def _eligible(account: dict[str, Any]) -> bool:
        return account["account_type"] in ELIGIBLE_ACCOUNT_TYPES and account["status"] == "ACTIVE"

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
