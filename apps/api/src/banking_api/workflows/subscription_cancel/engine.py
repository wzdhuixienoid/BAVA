from datetime import UTC, datetime
from uuid import UUID

from banking_api.domain.enums import WorkflowStatus
from banking_api.domain.principal import ExecutionPrincipal
from banking_api.subscriptions.contracts import next_billing
from banking_api.subscriptions.detector import normalize_merchant
from banking_api.subscriptions.models import SubscriptionAnalysisSnapshot
from banking_api.tools.executor import ToolExecutor
from banking_api.workflows.subscription_cancel.models import (
    SubscriptionCancelIntent,
    SubscriptionCancelRequiredInput,
    SubscriptionCancelRequiredInputType,
    SubscriptionCancelReviewPayload,
    SubscriptionCancelWorkflowState,
    SubscriptionCandidate,
)

SUBSCRIPTION_WORKFLOW_CALLER = "workflow:subscription-cancel"
SUBSCRIPTION_CAPABILITIES = frozenset(
    {
        "subscription.analyze",
        "subscription.cancel",
        "subscription.resume",
        "subscription.get_status",
    }
)


class SubscriptionCancellationWorkflowError(Exception):
    pass


class SubscriptionCancellationWorkflow:
    def __init__(self, executor: ToolExecutor) -> None:
        self.executor = executor

    async def start(
        self, intent: SubscriptionCancelIntent, *, principal: ExecutionPrincipal
    ) -> tuple[WorkflowStatus, SubscriptionCancelWorkflowState]:
        state = SubscriptionCancelWorkflowState(draft=intent.model_dump())
        return await self.advance(state, principal=principal)

    async def advance(
        self, state: SubscriptionCancelWorkflowState, *, principal: ExecutionPrincipal
    ) -> tuple[WorkflowStatus, SubscriptionCancelWorkflowState]:
        result = await self.executor.execute(
            tool_name="analyze_subscriptions",
            arguments={"upcoming_days": 90},
            caller=SUBSCRIPTION_WORKFLOW_CALLER,
            principal=principal,
            agent_allowlist=SUBSCRIPTION_CAPABILITIES,
        )
        if not result.ok or result.output is None:
            raise SubscriptionCancellationWorkflowError("SUBSCRIPTION_ANALYSIS_UNAVAILABLE")
        snapshot = SubscriptionAnalysisSnapshot.model_validate(result.output["snapshot"])
        query = normalize_merchant(state.draft.subscription_query)
        matches = [
            item
            for item in snapshot.subscriptions
            if query in normalize_merchant(item.merchant)
            or (
                item.plan_name is not None
                and query in normalize_merchant(f"{item.merchant}{item.plan_name}")
            )
        ]
        state.candidates = [
            SubscriptionCandidate(
                subscription_id=item.subscription_id,
                merchant=item.merchant,
                plan_name=item.plan_name,
                management_type=item.management_type.value,
                status=item.status.value,
                amount=item.last_charge_amount,
                currency=item.currency,
                cancellable=item.cancellable,
                resumable=item.resumable,
            )
            for item in matches
        ]
        selected = next(
            (
                item
                for item in matches
                if item.subscription_id is not None
                and item.subscription_id == state.draft.subscription_id
            ),
            None,
        )
        if state.draft.subscription_id is not None and selected is None:
            return self._failed(state, "SUBSCRIPTION_NOT_FOUND", "所选订阅不再可用。")
        if not matches:
            return self._failed(state, "SUBSCRIPTION_NOT_FOUND", "未找到匹配的订阅。")
        if selected is None and len(matches) > 1:
            state.required_input = SubscriptionCancelRequiredInput(
                type=SubscriptionCancelRequiredInputType.SUBSCRIPTION_SELECTION,
                message="找到多个匹配订阅，请明确选择。",
                options=state.candidates,
            )
            return WorkflowStatus.WAITING_FOR_INPUT, state
        selected = selected or matches[0]
        if selected.management_type.value != "MANAGED" or selected.subscription_id is None:
            return self._failed(
                state,
                "SUBSCRIPTION_NOT_MANAGED",
                "已检测到周期扣费，但当前银行沙箱没有该商户的可管理订阅合同。",
            )
        resume = state.draft.action == "SUBSCRIPTION_RESUME"
        if resume:
            if selected.status.value == "ACTIVE":
                return self._failed(state, "ALREADY_ACTIVE", "该订阅已经生效，无需重复订阅。")
            if not selected.resumable:
                return self._failed(
                    state, "SUBSCRIPTION_NOT_RESUMABLE", "该订阅当前不支持恢复，请到商户办理。"
                )
        else:
            if selected.status.value == "CANCELLED":
                return self._failed(state, "ALREADY_CANCELLED", "该订阅已取消。")
            if not selected.cancellable:
                return self._failed(state, "SUBSCRIPTION_NOT_CANCELLABLE", "该订阅当前不可取消。")
        billing_at = selected.next_billing_at
        if resume:
            previous = state.review_payload
            billing_at = (
                previous.next_billing_at
                if previous and previous.contract_version == selected.contract_version
                else next_billing(
                    {
                        "next_billing_at": selected.billing_anchor_at,
                        "billing_interval": selected.billing_interval.value,
                    },
                    datetime.now(UTC),
                )
            )
        state.draft.subscription_id = selected.subscription_id
        state.required_input = None
        state.error_code = None
        state.error_message = None
        state.review_payload = SubscriptionCancelReviewPayload(
            action=state.draft.action,
            contract_version=selected.contract_version,
            subscription_id=selected.subscription_id,
            user_id=principal.user_id,
            merchant=selected.merchant,
            plan_name=selected.plan_name,
            amount=selected.contract_amount
            if selected.contract_amount is not None
            else selected.last_charge_amount,
            currency=selected.currency,
            next_billing_at=billing_at,
        )
        return WorkflowStatus.READY_FOR_REVIEW, state

    async def submit_operation(
        self, operation_id: UUID, *, principal: ExecutionPrincipal
    ) -> dict[str, object]:
        result = await self.executor.execute(
            tool_name="cancel_subscription",
            arguments={"operation_id": str(operation_id)},
            caller=SUBSCRIPTION_WORKFLOW_CALLER,
            principal=principal,
            agent_allowlist=SUBSCRIPTION_CAPABILITIES,
        )
        if not result.ok or result.output is None:
            raise SubscriptionCancellationWorkflowError("SUBSCRIPTION_PROVIDER_UNAVAILABLE")
        return result.output

    async def submit_resume_operation(
        self, operation_id: UUID, *, principal: ExecutionPrincipal
    ) -> dict[str, object]:
        result = await self.executor.execute(
            tool_name="resume_subscription",
            arguments={"operation_id": str(operation_id)},
            caller=SUBSCRIPTION_WORKFLOW_CALLER,
            principal=principal,
            agent_allowlist=SUBSCRIPTION_CAPABILITIES,
        )
        if not result.ok or result.output is None:
            raise SubscriptionCancellationWorkflowError("SUBSCRIPTION_PROVIDER_UNAVAILABLE")
        return result.output

    async def query_operation_status(
        self, operation_id: UUID, *, principal: ExecutionPrincipal
    ) -> dict[str, object]:
        result = await self.executor.execute(
            tool_name="get_subscription_cancellation_status",
            arguments={"operation_id": str(operation_id)},
            caller=SUBSCRIPTION_WORKFLOW_CALLER,
            principal=principal,
            agent_allowlist=SUBSCRIPTION_CAPABILITIES,
        )
        if not result.ok or result.output is None:
            raise SubscriptionCancellationWorkflowError("SUBSCRIPTION_PROVIDER_UNAVAILABLE")
        return result.output

    @staticmethod
    def _failed(
        state: SubscriptionCancelWorkflowState, code: str, message: str
    ) -> tuple[WorkflowStatus, SubscriptionCancelWorkflowState]:
        state.error_code = code
        state.error_message = message
        state.review_payload = None
        state.required_input = None
        return WorkflowStatus.FAILED, state
