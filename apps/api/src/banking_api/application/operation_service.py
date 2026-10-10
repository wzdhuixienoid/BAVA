import hashlib
import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.application.operation_recovery_policy import OperationRecoveryPolicy
from banking_api.application.transfer_risk_facts import TransferRiskFactsService
from banking_api.audit.safety import workflow_evidence
from banking_api.config.settings import get_settings
from banking_api.domain.enums import (
    ApprovalStatus,
    OperationStatus,
    ReauthenticationStatus,
    WorkflowStatus,
)
from banking_api.domain.operation import OperationResource, OperationType
from banking_api.domain.principal import ExecutionPrincipal
from banking_api.domain.risk import BusinessRiskLevel, TransferRiskDecision
from banking_api.domain.workflow import WorkflowType
from banking_api.persistence.models import (
    AARequestModel,
    AAShareModel,
    OperationModel,
    ScheduledAuthorizationModel,
    ScheduledTransferModel,
    WorkflowModel,
)
from banking_api.persistence.repositories.approvals import ApprovalRepository
from banking_api.persistence.repositories.operations import OperationRepository
from banking_api.persistence.repositories.reauthentications import (
    ReauthenticationRepository,
)
from banking_api.persistence.repositories.workflows import WorkflowRepository
from banking_api.runtime.event_bus import EventBus
from banking_api.runtime.event_publisher import EventPublisher
from banking_api.security.guard import (
    SecurityGuardService,
    SecurityGuardStatus,
    SecurityWriteLockedError,
    acquire_security_user_lock,
)
from banking_api.workflows.subscription_cancel.authorization import (
    canonicalize_subscription_cancel_payload,
    subscription_cancel_payload_hash,
)
from banking_api.workflows.subscription_cancel.engine import (
    SubscriptionCancellationWorkflow,
    SubscriptionCancellationWorkflowError,
)
from banking_api.workflows.subscription_cancel.models import SubscriptionCancelWorkflowState
from banking_api.workflows.transfer.authorization import (
    canonicalize_transfer_payload,
    transfer_payload_hash,
)
from banking_api.workflows.transfer.engine import (
    TransferWorkflowEngine,
    TransferWorkflowEngineError,
)
from banking_api.workflows.transfer.models import TransferWorkflowState
from banking_api.workflows.transfer.risk import (
    TransferRiskCurrencyUnsupportedError,
    TransferRiskPolicy,
)


class OperationNotFoundError(Exception):
    pass


class OperationVersionConflictError(Exception):
    pass


class OperationActionError(Exception):
    pass


class OperationLeaseLostError(Exception):
    pass


logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def transfer_risk_lock_key(user_id: str) -> int:
    """Map one Principal to a stable signed PostgreSQL advisory-lock key."""

    digest = hashlib.sha256(f"transfer-risk:user:{user_id}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


class OperationService:
    """TRANSFER-only operation preparation, submission, and reconciliation."""

    def __init__(
        self,
        session: AsyncSession,
        bus: EventBus,
        engine: TransferWorkflowEngine,
        *,
        subscription_engine: SubscriptionCancellationWorkflow | None = None,
        clock=_now,  # type: ignore[no-untyped-def]
        recovery_policy: OperationRecoveryPolicy | None = None,
    ) -> None:
        self.session = session
        self.bus = bus
        self.engine = engine
        self.subscription_engine = subscription_engine
        self.clock = clock
        self.recovery_policy = recovery_policy or OperationRecoveryPolicy.from_settings()
        self.workflows = WorkflowRepository(session)
        self.approvals = ApprovalRepository(session)
        self.reauthentications = ReauthenticationRepository(session)
        self.operations = OperationRepository(session)
        self.publisher = EventPublisher(session)
        self.security_guard = SecurityGuardService(session, clock=clock)
        settings = get_settings()
        self.risk_facts = TransferRiskFactsService(
            session, business_timezone=settings.banking_business_timezone
        )
        self.risk_policy = TransferRiskPolicy()

    async def get(self, operation_id: UUID, *, user_id: str) -> OperationResource:
        model = await self.operations.get_for_user(operation_id, user_id)
        if model is None:
            raise OperationNotFoundError
        return self._resource(model)

    async def commit_workflow(
        self, workflow_id: UUID, *, user_id: str, expected_version: int
    ) -> OperationResource:
        workflow = await self.workflows.get_for_user(workflow_id, user_id)
        if workflow is None:
            raise OperationNotFoundError
        from banking_api.wealth.workflow import TYPES, WealthWorkflow

        if workflow.workflow_type in TYPES:
            op = await WealthWorkflow(
                self.session, self.engine.wealth_engine.balances, self.clock
            ).prepare(workflow_id, user_id, expected_version)
            return await self.reconcile(
                op.operation_id, user_id=user_id, expected_version=op.version
            )
        await acquire_security_user_lock(self.session, user_id)
        existing = await self.operations.get_for_workflow(workflow_id, user_id)
        if existing is not None:
            resource = self._resource(existing)
            await self.session.commit()
            return resource
        operation = (
            await self.prepare_subscription_cancel(
                workflow_id, user_id=user_id, expected_version=expected_version
            )
            if workflow.workflow_type
            in {WorkflowType.SUBSCRIPTION_CANCEL, WorkflowType.SUBSCRIPTION_RESUME}
            else await self.prepare_transfer(
                workflow_id, user_id=user_id, expected_version=expected_version
            )
        )
        return await self.reconcile(
            operation.operation_id,
            user_id=user_id,
            expected_version=operation.version,
        )

    async def prepare_transfer(
        self,
        workflow_id: UUID,
        *,
        user_id: str,
        expected_version: int,
        schedule_id: UUID | None = None,
        lease_owner: str | None = None,
    ) -> OperationResource:
        # Global lock order for transfer creation: Security Guard, then Transfer Risk.
        # Both transaction-scoped locks remain held through Operation creation and commit.
        await acquire_security_user_lock(self.session, user_id)
        existing = await self.operations.get_for_workflow(workflow_id, user_id)
        if existing is not None:
            resource = self._resource(existing)
            await self.session.commit()
            return resource
        await self._write_gate(workflow_id, user_id)
        await self._serialize_user_risk(user_id)
        workflow = await self.workflows.get_for_user_for_update(workflow_id, user_id)
        if workflow is None:
            raise OperationNotFoundError
        if workflow.version != expected_version:
            raise OperationVersionConflictError
        if workflow.status is not WorkflowStatus.READY_FOR_COMMIT:
            await self._record_bypass_if_security_control(workflow)
            raise OperationActionError("WORKFLOW_NOT_READY_FOR_COMMIT")
        if await self.operations.get_for_workflow(workflow_id, user_id) is not None:
            raise OperationActionError("TRANSFER_OPERATION_ALREADY_EXISTS")

        state = TransferWorkflowState.model_validate(workflow.state_json)
        scheduled = None
        grant = None
        if state.draft.schedule_requested:
            if schedule_id is None:
                raise OperationActionError("SCHEDULE_REQUIRES_SCOPED_AUTHORIZATION")
            from banking_api.application.schedule_service import require_mock_scheduling

            require_mock_scheduling(self.engine)
            scheduled = await self.session.get(
                ScheduledTransferModel, schedule_id, with_for_update=True
            )
            now = _as_utc(self.clock())
            if (
                scheduled is None
                or scheduled.user_id != user_id
                or scheduled.workflow_id != workflow_id
                or scheduled.status != "EXECUTING"
                or scheduled.lease_owner != lease_owner
                or scheduled.lease_expires_at is None
                or _as_utc(scheduled.lease_expires_at) <= now
            ):
                raise OperationActionError("SCHEDULE_LEASE_LOST")
            grant = await self.session.get(
                ScheduledAuthorizationModel,
                scheduled.authorization_id,
                with_for_update=True,
            )
            if (
                grant is None
                or grant.user_id != user_id
                or grant.workflow_id != workflow_id
                or grant.schedule_id != schedule_id
                or grant.used_at is not None
                or grant.revoked_at is not None
            ):
                raise OperationActionError("SCHEDULE_AUTHORIZATION_INVALID")
            if scheduled.series_id:
                from banking_api.application.schedule_service import validate_recurring_scope

                await validate_recurring_scope(self.session, scheduled, grant, user_id)
            if not _as_utc(scheduled.scheduled_for) <= now <= _as_utc(scheduled.execute_deadline):
                raise OperationActionError("SCHEDULE_OUTSIDE_EXECUTION_WINDOW")
            if (
                state.review_payload is None
                or transfer_payload_hash(state.review_payload) != grant.payload_hash
                or canonicalize_transfer_payload(state.review_payload) != grant.payload_json
            ):
                raise OperationActionError("SCHEDULE_AUTHORIZATION_SCOPE_MISMATCH")
        elif schedule_id is not None:
            raise OperationActionError("SCHEDULE_AUTHORIZATION_SCOPE_MISMATCH")
        authorization = state.authorization
        if authorization is None or state.review_payload is None:
            raise OperationActionError("TRANSFER_AUTHORIZATION_MISSING")
        try:
            self.risk_policy.require_supported_currency(state.review_payload.currency)
        except TransferRiskCurrencyUnsupportedError as exc:
            raise OperationActionError(exc.code) from exc
        approval = await self.approvals.get_for_workflow_user_for_update(
            authorization.approval_id, workflow_id, user_id
        )
        if approval is None:
            raise OperationActionError("APPROVAL_NOT_FOUND")
        now = _as_utc(self.clock())
        if grant is None and (
            approval.status is not ApprovalStatus.APPROVED or approval.consumed_at is not None
        ):
            raise OperationActionError("APPROVAL_NOT_CONSUMABLE")
        if grant is None and _as_utc(approval.expires_at) <= now:
            await self._expire_approval(workflow, state, approval)
            raise OperationActionError("APPROVAL_EXPIRED")
        initial_hash = transfer_payload_hash(state.review_payload)
        if (
            initial_hash != approval.payload_hash
            or initial_hash != authorization.approval_payload_hash
        ):
            raise OperationActionError("APPROVAL_PAYLOAD_MISMATCH")
        try:
            self.engine.ensure_commit_allowed()
        except TransferWorkflowEngineError as exc:
            raise OperationActionError("TRANSFER_COMMIT_POLICY_DENIED") from exc

        try:
            validation_status, state = await self.engine.advance(
                state, principal=ExecutionPrincipal.for_workflow(user_id), session=self.session
            )
        except TransferWorkflowEngineError as exc:
            raise OperationActionError("FINAL_VALIDATION_UNAVAILABLE") from exc
        if validation_status is not WorkflowStatus.READY_FOR_REVIEW or state.review_payload is None:
            await self._fail_final_validation(workflow, state)
            if state.validation is not None and any(
                issue.code == TransferRiskCurrencyUnsupportedError.code
                for issue in state.validation.issues
            ):
                raise OperationActionError(TransferRiskCurrencyUnsupportedError.code)
            raise OperationActionError("FINAL_TRANSFER_VALIDATION_FAILED")
        current_hash = transfer_payload_hash(state.review_payload)
        if current_hash != approval.payload_hash:
            raise OperationActionError("APPROVAL_PAYLOAD_MISMATCH")

        previous_level = state.risk_decision.level if state.risk_decision is not None else None
        facts = await self.risk_facts.for_user(
            user_id=user_id,
            currency=state.review_payload.currency,
            evaluated_at=now,
        )
        fresh_risk = self.risk_policy.evaluate(
            requested_amount=state.review_payload.amount,
            currency=state.review_payload.currency,
            business_date=facts.business_date,
            successful_transfer_total_today=facts.successful_total,
            in_flight_transfer_exposure_today=facts.in_flight_exposure,
            evaluated_at=now,
        )
        risk = self.risk_policy.retain_stricter(state.risk_decision, fresh_risk, at_commit=True)
        state.risk_decision = risk
        escalated = (
            previous_level is BusinessRiskLevel.YELLOW and risk.level is BusinessRiskLevel.RED
        )
        if risk.required_reauthentication and grant is None:
            if authorization.reauth_id is None:
                await self._require_reauthentication_for_risk(
                    workflow, state, risk, escalated=escalated
                )
                raise OperationActionError("TRANSFER_RISK_REAUTH_REQUIRED")
            reauth = await self.reauthentications.get_for_workflow_user_for_update(
                authorization.reauth_id, workflow_id, user_id
            )
            if reauth is None or reauth.approval_id != approval.approval_id:
                raise OperationActionError("REAUTH_APPROVAL_MISMATCH")
            if reauth.status is not ReauthenticationStatus.VERIFIED:
                raise OperationActionError("REAUTH_NOT_VERIFIED")
            if _as_utc(reauth.expires_at) <= now:
                await self._expire_reauthentication(workflow, state, reauth)
                raise OperationActionError("REAUTH_EXPIRED")

        aa_share = None
        if state.draft.aa_share_id:
            aa_share = await self.session.get(
                AAShareModel, state.draft.aa_share_id, with_for_update=True, populate_existing=True
            )
            if (
                aa_share is None
                or aa_share.user_id != user_id
                or aa_share.workflow_id != workflow_id
                or aa_share.status != "PENDING"
                or aa_share.operation_id
            ):
                raise OperationActionError("AA_SHARE_NOT_PAYABLE")
            aa_request = await self.session.get(AARequestModel, aa_share.request_id)
            if _as_utc(aa_request.deadline) <= now:
                raise OperationActionError("AA_EXPIRED")
        operation = await self.operations.create_transfer(
            user_id=user_id,
            workflow_id=workflow_id,
            approval_id=approval.approval_id,
            payload=canonicalize_transfer_payload(state.review_payload),
            payload_hash=current_hash,
            idempotency_key=uuid4(),
            next_reconcile_at=now,
            risk_business_date=state.risk_decision.business_date,
        )
        if aa_share is not None:
            aa_share.operation_id = operation.operation_id
            aa_share.status = "PROCESSING"
            await self.publisher.persist(
                event_type="aa.payment.operation.created",
                conversation_id=workflow.conversation_id,
                task_id=workflow.source_task_id,
                data={
                    "aa_request_id": str(aa_share.request_id),
                    "aa_share_id": str(aa_share.share_id),
                    "workflow_id": str(workflow_id),
                    "operation_id": str(operation.operation_id),
                },
            )
        if grant is not None:
            grant.used_at = now
            scheduled.operation_id = operation.operation_id
            scheduled.version += 1
            scheduled.lease_owner = None
            scheduled.lease_expires_at = None
        approval.status = ApprovalStatus.CONSUMED
        approval.consumed_at = now
        approval.consumed_by_operation_id = operation.operation_id
        updated = await self.workflows.update_if_version(
            workflow_id=workflow_id,
            user_id=user_id,
            expected_version=expected_version,
            status=WorkflowStatus.COMMITTING,
            state=state.model_dump(mode="json"),
        )
        if updated is None:
            await self.session.rollback()
            raise OperationVersionConflictError
        await self._risk_event(updated, risk, escalated=escalated)
        await self._operation_event(operation, "operation.created")
        await self._approval_consumed(updated, approval, operation)
        await self.publisher.persist(
            event_type="workflow.committing",
            conversation_id=workflow.conversation_id,
            task_id=workflow.source_task_id,
            data=self._workflow_event_data(updated),
        )
        await self.session.commit()
        return self._resource(operation)

    async def prepare_subscription_cancel(
        self, workflow_id: UUID, *, user_id: str, expected_version: int
    ) -> OperationResource:
        # The Security Guard lock is held until this Operation transaction commits.
        await acquire_security_user_lock(self.session, user_id)
        existing = await self.operations.get_for_workflow(workflow_id, user_id)
        if existing is not None:
            resource = self._resource(existing)
            await self.session.commit()
            return resource
        await self._write_gate(workflow_id, user_id)
        if self.subscription_engine is None:
            raise OperationActionError("SUBSCRIPTION_WORKFLOW_NOT_CONFIGURED")
        workflow = await self.workflows.get_for_user_for_update(workflow_id, user_id)
        if workflow is None:
            raise OperationNotFoundError
        if workflow.workflow_type not in {
            WorkflowType.SUBSCRIPTION_CANCEL,
            WorkflowType.SUBSCRIPTION_RESUME,
        }:
            raise OperationActionError("WORKFLOW_TYPE_MISMATCH")
        if workflow.version != expected_version:
            raise OperationVersionConflictError
        if workflow.status is not WorkflowStatus.READY_FOR_COMMIT:
            await self._record_bypass_if_security_control(workflow)
            raise OperationActionError("WORKFLOW_NOT_READY_FOR_COMMIT")
        if await self.operations.get_for_workflow(workflow_id, user_id) is not None:
            raise OperationActionError("SUBSCRIPTION_OPERATION_ALREADY_EXISTS")
        state = SubscriptionCancelWorkflowState.model_validate(workflow.state_json)
        if state.authorization is None or state.review_payload is None:
            raise OperationActionError("SUBSCRIPTION_AUTHORIZATION_MISSING")
        approval = await self.approvals.get_for_workflow_user_for_update(
            state.authorization.approval_id, workflow_id, user_id
        )
        if approval is None or approval.status is not ApprovalStatus.APPROVED:
            raise OperationActionError("APPROVAL_NOT_CONSUMABLE")
        now = _as_utc(self.clock())
        if _as_utc(approval.expires_at) <= now:
            await self._expire_approval(workflow, state, approval)
            raise OperationActionError("APPROVAL_EXPIRED")
        expected_hash = subscription_cancel_payload_hash(state.review_payload)
        if (
            approval.payload_hash != expected_hash
            or state.authorization.approval_payload_hash != expected_hash
        ):
            raise OperationActionError("APPROVAL_PAYLOAD_MISMATCH")
        validation_status, state = await self.subscription_engine.advance(
            state, principal=ExecutionPrincipal.for_workflow(user_id)
        )
        if validation_status is not WorkflowStatus.READY_FOR_REVIEW or state.review_payload is None:
            await self._fail_final_validation(workflow, state)
            raise OperationActionError(state.error_code or "SUBSCRIPTION_REVALIDATION_FAILED")
        if subscription_cancel_payload_hash(state.review_payload) != approval.payload_hash:
            await self._expire_approval(workflow, state, approval)
            raise OperationActionError("APPROVAL_PAYLOAD_MISMATCH")
        resume = workflow.workflow_type is WorkflowType.SUBSCRIPTION_RESUME
        if (
            state.draft.action != workflow.workflow_type.value
            or state.review_payload.action != workflow.workflow_type.value
        ):
            raise OperationActionError("WORKFLOW_TYPE_MISMATCH")
        if resume:
            authorization = state.authorization
            if authorization.reauth_id is None:
                raise OperationActionError("REAUTH_REQUIRED")
            reauth = await self.reauthentications.get_for_workflow_user_for_update(
                authorization.reauth_id, workflow_id, user_id
            )
            if reauth is None or reauth.approval_id != approval.approval_id:
                raise OperationActionError("REAUTH_APPROVAL_MISMATCH")
            if reauth.status is not ReauthenticationStatus.VERIFIED:
                raise OperationActionError("REAUTH_NOT_VERIFIED")
            if _as_utc(reauth.expires_at) <= now:
                await self._expire_reauthentication(workflow, state, reauth)
                raise OperationActionError("REAUTH_EXPIRED")
        operation = await self.operations.create_subscription_cancel(
            user_id=user_id,
            workflow_id=workflow_id,
            approval_id=approval.approval_id,
            payload=canonicalize_subscription_cancel_payload(state.review_payload),
            payload_hash=expected_hash,
            idempotency_key=uuid4(),
            next_reconcile_at=now,
            resume=resume,
        )
        approval.status = ApprovalStatus.CONSUMED
        approval.consumed_at = now
        approval.consumed_by_operation_id = operation.operation_id
        updated = await self.workflows.update_if_version(
            workflow_id=workflow_id,
            user_id=user_id,
            expected_version=expected_version,
            status=WorkflowStatus.COMMITTING,
            state=state.model_dump(mode="json"),
        )
        if updated is None:
            await self.session.rollback()
            raise OperationVersionConflictError
        await self._operation_event(operation, "operation.created")
        await self._approval_consumed(updated, approval, operation)
        await self.publisher.persist(
            event_type="workflow.committing",
            conversation_id=workflow.conversation_id,
            task_id=workflow.source_task_id,
            data=self._workflow_event_data(updated),
        )
        await self.session.commit()
        return self._resource(operation)

    async def _serialize_user_risk(self, user_id: str) -> None:
        if self.session.get_bind().dialect.name != "postgresql":
            return
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": transfer_risk_lock_key(user_id)},
        )

    async def _record_bypass_if_security_control(self, workflow: WorkflowModel) -> None:
        if workflow.status not in {
            WorkflowStatus.READY_FOR_REVIEW,
            WorkflowStatus.REAUTH_REQUIRED,
        }:
            return
        status = await self.security_guard.record_control_bypass_attempt(
            user_id=workflow.user_id,
            workflow_id=workflow.workflow_id,
            conversation_id=workflow.conversation_id,
            task_id=workflow.source_task_id,
        )
        await self.session.commit()
        if status.status is SecurityGuardStatus.WRITE_LOCKED:
            raise SecurityWriteLockedError(status)

    async def _require_reauthentication_for_risk(
        self,
        workflow: WorkflowModel,
        state: TransferWorkflowState,
        decision: TransferRiskDecision,
        *,
        escalated: bool,
    ) -> None:
        updated = await self.workflows.update_if_version(
            workflow_id=workflow.workflow_id,
            user_id=workflow.user_id,
            expected_version=workflow.version,
            status=WorkflowStatus.REAUTH_REQUIRED,
            state=state.model_dump(mode="json"),
        )
        if updated is None:
            await self.session.rollback()
            raise OperationVersionConflictError
        await self._risk_event(updated, decision, escalated=escalated)
        await self.publisher.persist(
            event_type="workflow.reauth_required",
            conversation_id=workflow.conversation_id,
            task_id=workflow.source_task_id,
            data=self._workflow_event_data(updated),
        )
        await self.session.commit()

    async def _risk_event(
        self,
        workflow: WorkflowModel,
        decision: TransferRiskDecision,
        *,
        escalated: bool,
    ):  # type: ignore[no-untyped-def]
        data = decision.model_dump(mode="json")
        data["workflow_id"] = str(workflow.workflow_id)
        data["version"] = workflow.version
        return await self.publisher.persist(
            event_type=("workflow.risk_escalated" if escalated else "workflow.risk_evaluated"),
            conversation_id=workflow.conversation_id,
            task_id=workflow.source_task_id,
            data=data,
        )

    async def reconcile(
        self, operation_id: UUID, *, user_id: str, expected_version: int
    ) -> OperationResource:
        lease_owner = f"manual:{uuid4()}"
        operation = await self.operations.get_for_user(operation_id, user_id, for_update=True)
        if operation is None:
            raise OperationNotFoundError
        if operation.version != expected_version:
            raise OperationVersionConflictError
        if operation.status in {OperationStatus.SUCCEEDED, OperationStatus.FAILED}:
            resource = self._resource(operation)
            await self.session.rollback()
            return resource

        now = _as_utc(self.clock())
        if (
            operation.lease_owner is not None
            and operation.lease_expires_at is not None
            and _as_utc(operation.lease_expires_at) > now
        ):
            await self.session.rollback()
            raise OperationActionError("OPERATION_RECONCILIATION_IN_PROGRESS")
        reclaimed = operation.lease_expires_at is not None
        operation.lease_owner = lease_owner
        operation.lease_expires_at = now + self.recovery_policy.lease_duration
        await self.session.commit()
        logger.info(
            "operation claimed operation_id=%s worker=%s reclaimed=%s",
            operation_id,
            lease_owner,
            reclaimed,
        )
        return await self.reconcile_claimed(operation_id, lease_owner=lease_owner)

    async def reconcile_claimed(self, operation_id: UUID, *, lease_owner: str) -> OperationResource:
        operation = await self.operations.get_claimed(
            operation_id, lease_owner, lease_valid_at=_as_utc(self.clock())
        )
        if operation is None:
            await self.session.rollback()
            raise OperationLeaseLostError
        if operation.status in {OperationStatus.SUCCEEDED, OperationStatus.FAILED}:
            resource = self._resource(operation)
            await self.session.rollback()
            return resource
        await self._operation_event(operation, "operation.reconcile_started")
        # End the snapshot transaction before any provider/network I/O.
        await self.session.commit()
        logger.info(
            "operation reconciliation attempt operation_id=%s status=%s worker=%s",
            operation_id,
            operation.status.value,
            lease_owner,
        )

        if operation.operation_type in {OperationType.WEALTH_PURCHASE, OperationType.WEALTH_REDEEM}:
            from banking_api.wealth.recovery import reconcile_wealth

            return await reconcile_wealth(self, operation, lease_owner)
        if operation.status is OperationStatus.CREATED:
            operation = await self._submit_created(operation, lease_owner=lease_owner)
            if operation.status is not OperationStatus.SUBMITTED:
                return self._resource(operation)
        return await self._query_status(operation, lease_owner=lease_owner)

    async def _submit_created(
        self, operation: OperationModel, *, lease_owner: str
    ) -> OperationModel:
        now = _as_utc(self.clock())
        await self._operation_event(operation, "provider.submit_started")
        await self.session.commit()
        try:
            operation_engine = self._operation_engine(operation.operation_type)
            submit = (
                operation_engine.submit_resume_operation
                if operation.operation_type is OperationType.SUBSCRIPTION_RESUME
                else operation_engine.submit_operation
            )
            output = await submit(
                operation.operation_id,
                principal=ExecutionPrincipal.for_recovery(operation.user_id),
            )
        except (TransferWorkflowEngineError, SubscriptionCancellationWorkflowError):
            logger.warning(
                "provider submission unavailable operation_id=%s", operation.operation_id
            )
            output = {"outcome": "UNKNOWN", "error_code": "SUBMISSION_AMBIGUOUS"}
        outcome = output["outcome"]
        if outcome == "ACCEPTED":
            status = OperationStatus.SUBMITTED
            submitted_at = now
            completed_at = None
            event_type = "operation.submitted"
        elif outcome == "FAILED":
            status = OperationStatus.FAILED
            submitted_at = None
            completed_at = now
            event_type = "operation.failed"
        else:
            status = OperationStatus.UNKNOWN
            submitted_at = None
            completed_at = None
            event_type = "operation.unknown"
        return await self._transition(
            operation,
            status=status,
            provider_reference=output.get("provider_reference"),
            error_code=output.get("error_code"),
            error_message=output.get("error_message"),
            submitted_at=submitted_at,
            completed_at=completed_at,
            event_type=event_type,
            lease_owner=lease_owner,
            finalize_attempt=status is not OperationStatus.SUBMITTED,
        )

    async def _query_status(
        self, operation: OperationModel, *, lease_owner: str
    ) -> OperationResource:
        try:
            operation_engine = self._operation_engine(operation.operation_type)
            output = await operation_engine.query_operation_status(
                operation.operation_id,
                principal=ExecutionPrincipal.for_recovery(operation.user_id),
            )
        except (TransferWorkflowEngineError, SubscriptionCancellationWorkflowError):
            logger.warning(
                "provider status query unavailable operation_id=%s", operation.operation_id
            )
            output = {"status": "UNKNOWN", "error_code": "STATUS_UNAVAILABLE"}
        provider_status = output["status"]
        now = _as_utc(self.clock())
        if provider_status == "SUCCEEDED":
            status = OperationStatus.SUCCEEDED
            completed_at = now
            event_type = "operation.succeeded"
        elif provider_status == "FAILED":
            status = OperationStatus.FAILED
            completed_at = now
            event_type = "operation.failed"
        elif provider_status == "PENDING":
            status = OperationStatus.SUBMITTED
            completed_at = None
            event_type = "operation.submitted"
        else:
            status = OperationStatus.UNKNOWN
            completed_at = None
            event_type = "operation.unknown"
        updated = await self._transition(
            operation,
            status=status,
            provider_reference=output.get("provider_reference") or operation.provider_reference,
            error_code=output.get("error_code"),
            error_message=output.get("error_message"),
            submitted_at=operation.submitted_at,
            completed_at=completed_at,
            event_type=event_type,
            lease_owner=lease_owner,
            finalize_attempt=True,
        )
        return self._resource(updated)

    async def _transition(
        self,
        operation: OperationModel,
        *,
        status: OperationStatus,
        provider_reference: str | None,
        error_code: str | None,
        error_message: str | None,
        submitted_at: datetime | None,
        completed_at: datetime | None,
        event_type: str,
        lease_owner: str,
        finalize_attempt: bool,
    ) -> OperationModel:
        now = _as_utc(self.clock())
        claimed = await self.operations.get_claimed(
            operation.operation_id,
            lease_owner,
            lease_valid_at=now,
            for_update=True,
        )
        if claimed is None or claimed.version != operation.version:
            await self.session.rollback()
            raise OperationLeaseLostError
        workflow = await self.workflows.get_for_user_for_update(
            claimed.workflow_id, claimed.user_id
        )
        if workflow is None:
            raise OperationNotFoundError
        terminal = status in {OperationStatus.SUCCEEDED, OperationStatus.FAILED}
        attempt_count = claimed.reconcile_attempts + (1 if finalize_attempt else 0)
        next_reconcile_at = claimed.next_reconcile_at
        if terminal:
            next_reconcile_at = None
        elif finalize_attempt:
            next_reconcile_at = now + self.recovery_policy.retry_delay(attempt_count)
        updated_operation = await self.operations.update_if_version(
            operation_id=claimed.operation_id,
            user_id=claimed.user_id,
            expected_version=claimed.version,
            status=status,
            provider_reference=provider_reference,
            error_code=error_code,
            error_message=error_message,
            submitted_at=submitted_at,
            completed_at=completed_at,
            lease_owner=lease_owner,
            reconcile_attempts=attempt_count,
            last_reconcile_at=now if finalize_attempt else claimed.last_reconcile_at,
            next_reconcile_at=next_reconcile_at,
            release_lease=finalize_attempt or terminal,
            lease_valid_at=now,
            retained_lease_expires_at=now + self.recovery_policy.lease_duration,
        )
        if updated_operation is None:
            await self.session.rollback()
            raise OperationVersionConflictError
        workflow_status = (
            WorkflowStatus.SUCCEEDED
            if status is OperationStatus.SUCCEEDED
            else WorkflowStatus.FAILED
            if status is OperationStatus.FAILED
            else WorkflowStatus.COMMITTING
        )
        updated_workflow = await self.workflows.update_if_version(
            workflow_id=workflow.workflow_id,
            user_id=workflow.user_id,
            expected_version=workflow.version,
            status=workflow_status,
            state=workflow.state_json,
        )
        if updated_workflow is None:
            await self.session.rollback()
            raise OperationVersionConflictError
        if terminal:
            from banking_api.application.notification_service import notify_schedule_result

            scheduled = await self.session.scalar(
                select(ScheduledTransferModel).where(
                    ScheduledTransferModel.operation_id == updated_operation.operation_id
                )
            )
            if scheduled is not None:
                await notify_schedule_result(self.session, scheduled, workflow, status.value, now)
        await self._operation_event(updated_operation, event_type)
        workflow_event_type = {
            WorkflowStatus.SUCCEEDED: "workflow.succeeded",
            WorkflowStatus.FAILED: "workflow.failed",
        }.get(workflow_status, "workflow.committing")
        await self.publisher.persist(
            event_type=workflow_event_type,
            conversation_id=workflow.conversation_id,
            task_id=workflow.source_task_id,
            data=self._workflow_event_data(updated_workflow),
        )
        await self.session.commit()
        if terminal:
            logger.info(
                "operation reconciliation terminal operation_id=%s status=%s attempts=%s",
                updated_operation.operation_id,
                updated_operation.status.value,
                updated_operation.reconcile_attempts,
            )
        elif finalize_attempt:
            logger.info(
                "operation reconciliation remains non-terminal operation_id=%s "
                "status=%s attempts=%s next_reconcile_at=%s",
                updated_operation.operation_id,
                updated_operation.status.value,
                updated_operation.reconcile_attempts,
                updated_operation.next_reconcile_at,
            )
        return updated_operation

    def _operation_engine(self, operation_type: OperationType):  # type: ignore[no-untyped-def]
        if operation_type is OperationType.TRANSFER:
            return self.engine
        if (
            operation_type in {OperationType.SUBSCRIPTION_CANCEL, OperationType.SUBSCRIPTION_RESUME}
            and self.subscription_engine
        ):
            return self.subscription_engine
        raise OperationActionError("OPERATION_TYPE_NOT_CONFIGURED")

    async def _expire_approval(self, workflow, state, approval) -> None:  # type: ignore[no-untyped-def]
        approval.status = ApprovalStatus.EXPIRED
        resource_events: list[tuple[str, dict[str, object]]] = [
            (
                "approval.expired",
                {
                    "workflow_id": str(workflow.workflow_id),
                    "approval_id": str(approval.approval_id),
                    "status": approval.status.value,
                    "expires_at": approval.expires_at.isoformat(),
                },
            )
        ]
        if state.authorization is not None and state.authorization.reauth_id is not None:
            reauth = await self.reauthentications.get_for_workflow_user_for_update(
                state.authorization.reauth_id, workflow.workflow_id, workflow.user_id
            )
            if reauth is not None and reauth.status in {
                ReauthenticationStatus.PENDING,
                ReauthenticationStatus.VERIFIED,
            }:
                reauth.status = ReauthenticationStatus.INVALIDATED
                resource_events.append(
                    (
                        "reauth.invalidated",
                        {
                            "workflow_id": str(workflow.workflow_id),
                            "reauth_id": str(reauth.reauth_id),
                            "status": reauth.status.value,
                        },
                    )
                )
        state.authorization = None
        await self._persist_safe_workflow_transition(
            workflow,
            state,
            WorkflowStatus.READY_FOR_REVIEW,
            "workflow.ready_for_review",
            resource_events=resource_events,
        )

    async def _expire_reauthentication(self, workflow, state, reauth) -> None:  # type: ignore[no-untyped-def]
        reauth.status = ReauthenticationStatus.EXPIRED
        assert state.authorization is not None
        state.authorization.reauth_id = None
        state.authorization.reauth_verified_at = None
        state.authorization.reauth_expires_at = None
        await self._persist_safe_workflow_transition(
            workflow,
            state,
            WorkflowStatus.REAUTH_REQUIRED,
            "workflow.reauth_required",
            resource_events=[
                (
                    "reauth.expired",
                    {
                        "workflow_id": str(workflow.workflow_id),
                        "reauth_id": str(reauth.reauth_id),
                        "status": reauth.status.value,
                        "expires_at": reauth.expires_at.isoformat(),
                    },
                )
            ],
        )

    async def _fail_final_validation(
        self, workflow: WorkflowModel, state: TransferWorkflowState
    ) -> None:
        await self._persist_safe_workflow_transition(
            workflow, state, WorkflowStatus.FAILED, "workflow.failed"
        )

    async def _persist_safe_workflow_transition(
        self,
        workflow: WorkflowModel,
        state: TransferWorkflowState,
        status: WorkflowStatus,
        event_type: str,
        *,
        resource_events: list[tuple[str, dict[str, object]]] | None = None,
    ) -> None:
        updated = await self.workflows.update_if_version(
            workflow_id=workflow.workflow_id,
            user_id=workflow.user_id,
            expected_version=workflow.version,
            status=status,
            state=state.model_dump(mode="json"),
        )
        if updated is None:
            await self.session.rollback()
            raise OperationVersionConflictError
        for resource_event_type, data in resource_events or []:
            await self.publisher.persist(
                event_type=resource_event_type,
                conversation_id=workflow.conversation_id,
                task_id=workflow.source_task_id,
                data=data,
            )
        await self.publisher.persist(
            event_type=event_type,
            conversation_id=workflow.conversation_id,
            task_id=workflow.source_task_id,
            data=self._workflow_event_data(updated),
        )
        await self.session.commit()

    async def _operation_event(self, operation: OperationModel, event_type: str):  # type: ignore[no-untyped-def]
        workflow = await self.workflows.get_for_user(operation.workflow_id, operation.user_id)
        if workflow is None:
            raise OperationNotFoundError
        data: dict[str, object] = {
            "operation_id": str(operation.operation_id),
            "workflow_id": str(operation.workflow_id),
            "operation_type": operation.operation_type.value,
            "status": operation.status.value,
            "version": operation.version,
            "payload_hash": operation.payload_hash,
            "provider_mode": "Mock",
            "actor_type": "USER"
            if (operation.lease_owner or "").startswith("manual:")
            else "RECOVERY_WORKER",
        }
        if operation.payload_json.get("aa_share_id"):
            data["aa_request_id"] = operation.payload_json["aa_request_id"]
            data["aa_share_id"] = operation.payload_json["aa_share_id"]
            if event_type in {
                "operation.created",
                "operation.succeeded",
                "operation.failed",
                "operation.unknown",
            }:
                group = await self.session.get(
                    AARequestModel, UUID(operation.payload_json["aa_request_id"])
                )
                await self.publisher.persist(
                    event_type="aa.payment." + event_type.removeprefix("operation."),
                    conversation_id=group.conversation_id,
                    task_id=group.source_task_id,
                    data=data,
                )
        if operation.provider_reference is not None:
            data["provider_reference"] = operation.provider_reference
        if operation.error_code is not None:
            data["error_code"] = operation.error_code
        return await self.publisher.persist(
            event_type=event_type,
            conversation_id=workflow.conversation_id,
            task_id=workflow.source_task_id,
            data=data,
        )

    @staticmethod
    def _workflow_event_data(model: WorkflowModel) -> dict[str, object]:
        return {
            "workflow_id": str(model.workflow_id),
            "workflow_type": model.workflow_type.value,
            "status": model.status.value,
            "version": model.version,
            "evidence": workflow_evidence(model.state_json),
        }

    async def _write_gate(self, workflow_id: UUID, user_id: str) -> None:
        model = await self.workflows.get_for_user(workflow_id, user_id)
        if model is None:
            raise OperationNotFoundError
        await self.security_guard.require_write_allowed(
            user_id,
            workflow_id=model.workflow_id,
            conversation_id=model.conversation_id,
            task_id=model.source_task_id,
        )

    async def _approval_consumed(self, workflow, approval, operation) -> None:
        await self.publisher.persist(
            event_type="approval.consumed",
            conversation_id=workflow.conversation_id,
            task_id=workflow.source_task_id,
            data={
                "workflow_id": str(workflow.workflow_id),
                "approval_id": str(approval.approval_id),
                "operation_id": str(operation.operation_id),
                "status": approval.status.value,
                "payload_hash": approval.payload_hash,
                "consumed_at": approval.consumed_at.isoformat(),
            },
        )

    @staticmethod
    def _resource(model: OperationModel) -> OperationResource:
        return OperationResource(
            operation_id=model.operation_id,
            workflow_id=model.workflow_id,
            operation_type=model.operation_type,
            status=model.status,
            version=model.version,
            provider_reference=model.provider_reference,
            error_code=model.error_code,
            error_message=model.error_message,
            created_at=model.created_at,
            submitted_at=model.submitted_at,
            completed_at=model.completed_at,
            next_reconcile_at=model.next_reconcile_at,
            reconcile_attempts=model.reconcile_attempts,
            last_reconcile_at=model.last_reconcile_at,
            updated_at=model.updated_at,
        )
