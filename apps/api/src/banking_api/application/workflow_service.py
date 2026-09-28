from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.application.transfer_risk_facts import TransferRiskFactsService
from banking_api.config.settings import get_settings
from banking_api.domain.approval import ApprovalSummary
from banking_api.domain.enums import (
    ApprovalStatus,
    ReauthenticationStatus,
    WorkflowStatus,
)
from banking_api.domain.operation import OperationSummary
from banking_api.domain.principal import ExecutionPrincipal
from banking_api.domain.reauthentication import ReauthenticationSummary
from banking_api.domain.risk import BusinessRiskLevel, TransferRiskDecision
from banking_api.domain.workflow import Workflow, WorkflowType
from banking_api.persistence.models import ApprovalModel, ReauthenticationModel, WorkflowModel
from banking_api.persistence.repositories.approvals import ApprovalRepository
from banking_api.persistence.repositories.operations import OperationRepository
from banking_api.persistence.repositories.reauthentications import (
    ReauthenticationRepository,
)
from banking_api.persistence.repositories.workflows import WorkflowRepository
from banking_api.runtime.event_bus import EventBus
from banking_api.runtime.event_publisher import EventPublisher
from banking_api.security.reauthentication.mock_provider import (
    MockReauthenticationProvider,
)
from banking_api.security.reauthentication.provider import ReauthenticationProvider
from banking_api.workflows.transfer.authorization import (
    canonicalize_transfer_payload,
    transfer_payload_hash,
)
from banking_api.workflows.transfer.engine import (
    InvalidWorkflowActionError,
    TransferWorkflowEngine,
)
from banking_api.workflows.transfer.models import (
    TransferAuthorizationSnapshot,
    TransferIntent,
    TransferWorkflowState,
)
from banking_api.workflows.transfer.risk import TransferRiskPolicy


class WorkflowNotFoundError(Exception):
    pass


class WorkflowVersionConflictError(Exception):
    pass


class WorkflowActionError(Exception):
    pass


Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class WorkflowService:
    """Orchestrates deterministic transfer actions; it cannot move money."""

    def __init__(
        self,
        session: AsyncSession,
        bus: EventBus,
        engine: TransferWorkflowEngine,
        *,
        reauth_provider: ReauthenticationProvider | None = None,
        clock: Clock = _utc_now,
        approval_ttl_seconds: int | None = None,
        reauth_ttl_seconds: int | None = None,
        reauth_max_attempts: int | None = None,
    ) -> None:
        settings = get_settings()
        self.session = session
        self.workflows = WorkflowRepository(session)
        self.approvals = ApprovalRepository(session)
        self.operations = OperationRepository(session)
        self.reauthentications = ReauthenticationRepository(session)
        self.publisher = EventPublisher(session)
        self.engine = engine
        self.reauth_provider = reauth_provider or MockReauthenticationProvider(
            settings.mock_reauth_code
        )
        self.clock = clock
        self.approval_ttl = timedelta(
            seconds=(
                settings.transfer_approval_ttl_seconds
                if approval_ttl_seconds is None
                else approval_ttl_seconds
            )
        )
        self.reauth_ttl = timedelta(
            seconds=(
                settings.transfer_reauth_ttl_seconds
                if reauth_ttl_seconds is None
                else reauth_ttl_seconds
            )
        )
        self.reauth_max_attempts = (
            settings.transfer_reauth_max_attempts
            if reauth_max_attempts is None
            else reauth_max_attempts
        )
        self.risk_facts = TransferRiskFactsService(
            session, business_timezone=settings.banking_business_timezone
        )
        self.risk_policy = TransferRiskPolicy()

    async def get(self, workflow_id: UUID, *, user_id: str) -> Workflow:
        model = await self.workflows.get_for_user(workflow_id, user_id)
        if model is None:
            raise WorkflowNotFoundError
        return await self._to_workflow(model)

    async def get_by_source_task(self, source_task_id: UUID, *, user_id: str) -> Workflow | None:
        model = await self.workflows.get_by_source_task(source_task_id, user_id)
        if model is None:
            return None
        return await self._to_workflow(model)

    async def list(self, *, user_id: str, conversation_id: UUID | None = None) -> list[Workflow]:
        models = await self.workflows.list_for_user(user_id, conversation_id)
        return [await self._to_workflow(model) for model in models]

    async def create_transfer(
        self,
        *,
        user_id: str,
        conversation_id: UUID,
        source_task_id: UUID,
        intent: TransferIntent,
    ) -> Workflow:
        initial = TransferWorkflowState(draft=intent.model_dump())
        model = await self.workflows.create(
            user_id=user_id,
            conversation_id=conversation_id,
            source_task_id=source_task_id,
            workflow_type=WorkflowType.TRANSFER,
            status=WorkflowStatus.DRAFT,
            state=initial.model_dump(mode="json"),
        )
        await self.publisher.persist(
            event_type="workflow.created",
            conversation_id=conversation_id,
            task_id=source_task_id,
            data=self._event_data(model),
        )
        status, state = await self.engine.advance(
            initial, principal=ExecutionPrincipal.for_workflow(user_id)
        )
        if status is WorkflowStatus.READY_FOR_REVIEW:
            await self._evaluate_transfer_risk(state, user_id=user_id)
        updated = await self.workflows.update_if_version(
            workflow_id=model.workflow_id,
            user_id=user_id,
            expected_version=model.version,
            status=status,
            state=state.model_dump(mode="json"),
        )
        if updated is None:
            raise WorkflowVersionConflictError
        await self.publisher.persist(
            event_type=self._workflow_event_type(status),
            conversation_id=conversation_id,
            task_id=source_task_id,
            data=self._event_data(updated),
        )
        if state.risk_decision is not None:
            await self._persist_risk_event(updated, state.risk_decision, escalated=False)
        await self.session.commit()
        return await self._to_workflow(updated)

    async def set_recipient_query(
        self,
        workflow_id: UUID,
        *,
        user_id: str,
        recipient_query: str,
        expected_version: int,
    ) -> Workflow:
        model, state = await self._load_action(workflow_id, user_id, expected_version)
        state.draft.recipient_query = recipient_query.strip()
        state.draft.payee_id = None
        return await self._mutate_and_advance(model, state, expected_version)

    async def select_payee(
        self,
        workflow_id: UUID,
        *,
        user_id: str,
        payee_id: str,
        expected_version: int,
    ) -> Workflow:
        model, state = await self._load_action(workflow_id, user_id, expected_version)
        try:
            await self.engine.validate_payee_action(
                state,
                payee_id,
                principal=ExecutionPrincipal.for_workflow(user_id),
                allow_outside_selection=self._is_review_or_authorization(model.status),
            )
        except InvalidWorkflowActionError as exc:
            raise WorkflowActionError(str(exc)) from exc
        state.draft.payee_id = payee_id
        return await self._mutate_and_advance(model, state, expected_version)

    async def select_source_account(
        self,
        workflow_id: UUID,
        *,
        user_id: str,
        account_id: str,
        expected_version: int,
    ) -> Workflow:
        model, state = await self._load_action(workflow_id, user_id, expected_version)
        try:
            await self.engine.validate_account_action(
                state,
                account_id,
                principal=ExecutionPrincipal.for_workflow(user_id),
                allow_outside_selection=self._is_review_or_authorization(model.status),
            )
        except InvalidWorkflowActionError as exc:
            raise WorkflowActionError(str(exc)) from exc
        state.draft.source_account_id = account_id
        return await self._mutate_and_advance(model, state, expected_version)

    async def set_amount(
        self,
        workflow_id: UUID,
        *,
        user_id: str,
        amount: Decimal,
        expected_version: int,
    ) -> Workflow:
        model, state = await self._load_action(workflow_id, user_id, expected_version)
        state.draft.amount = amount
        return await self._mutate_and_advance(model, state, expected_version)

    async def approve(self, workflow_id: UUID, *, user_id: str, expected_version: int) -> Workflow:
        model, state = await self._load_action(workflow_id, user_id, expected_version)
        if model.status is not WorkflowStatus.READY_FOR_REVIEW or state.review_payload is None:
            raise WorkflowActionError("WORKFLOW_NOT_READY_FOR_APPROVAL")

        validation_status, state = await self.engine.advance(
            state, principal=ExecutionPrincipal.for_workflow(user_id)
        )
        if validation_status is not WorkflowStatus.READY_FOR_REVIEW or state.review_payload is None:
            updated = await self.workflows.update_if_version(
                workflow_id=workflow_id,
                user_id=user_id,
                expected_version=expected_version,
                status=validation_status,
                state=state.model_dump(mode="json"),
            )
            if updated is None:
                await self.session.rollback()
                raise WorkflowVersionConflictError
            await self.publisher.persist(
                event_type=self._workflow_event_type(validation_status),
                conversation_id=model.conversation_id,
                task_id=model.source_task_id,
                data=self._event_data(updated),
            )
            await self.session.commit()
            raise WorkflowActionError("TRANSFER_REVALIDATION_FAILED")

        now = _as_utc(self.clock())
        previous_level = state.risk_decision.level if state.risk_decision is not None else None
        decision = await self._evaluate_transfer_risk(state, user_id=user_id)
        await self._invalidate_authorization(model, now)
        canonical_payload = canonicalize_transfer_payload(state.review_payload)
        payload_hash = transfer_payload_hash(state.review_payload)
        approval = await self.approvals.create_pending(
            user_id=user_id,
            workflow_id=workflow_id,
            payload=canonical_payload,
            payload_hash=payload_hash,
            expires_at=now + self.approval_ttl,
        )
        await self._persist_authorization_event(
            model,
            "approval.created",
            approval_id=approval.approval_id,
            status=approval.status.value,
            expires_at=approval.expires_at,
        )
        approval.status = ApprovalStatus.APPROVED
        approval.approved_at = now
        state.authorization = TransferAuthorizationSnapshot(
            approval_id=approval.approval_id,
            approval_payload_hash=payload_hash,
            approval_expires_at=approval.expires_at,
        )
        next_status = (
            WorkflowStatus.REAUTH_REQUIRED
            if decision.required_reauthentication
            else WorkflowStatus.READY_FOR_COMMIT
        )
        updated = await self.workflows.update_if_version(
            workflow_id=workflow_id,
            user_id=user_id,
            expected_version=expected_version,
            status=next_status,
            state=state.model_dump(mode="json"),
        )
        if updated is None:
            await self.session.rollback()
            raise WorkflowVersionConflictError
        await self._persist_authorization_event(
            updated,
            "approval.approved",
            approval_id=approval.approval_id,
            status=approval.status.value,
            expires_at=approval.expires_at,
        )
        await self._persist_risk_event(
            updated,
            decision,
            escalated=(
                previous_level is BusinessRiskLevel.YELLOW
                and decision.level is BusinessRiskLevel.RED
            ),
        )
        await self.publisher.persist(
            event_type=self._workflow_event_type(next_status),
            conversation_id=model.conversation_id,
            task_id=model.source_task_id,
            data=self._event_data(updated),
        )
        await self.session.commit()
        return await self._to_workflow(updated)

    async def start_reauthentication(
        self, workflow_id: UUID, *, user_id: str, expected_version: int
    ) -> Workflow:
        model, state = await self._load_action(workflow_id, user_id, expected_version)
        if model.status is not WorkflowStatus.REAUTH_REQUIRED:
            raise WorkflowActionError("WORKFLOW_NOT_REAUTH_REQUIRED")
        approval = await self._require_current_approval(model, state)
        current = await self.reauthentications.latest_for_workflow(workflow_id, user_id)
        if current is not None and current.status is ReauthenticationStatus.PENDING:
            if _as_utc(current.expires_at) > _as_utc(self.clock()):
                raise WorkflowActionError("REAUTH_ALREADY_PENDING")
            await self._expire_reauthentication(model, state, current, expected_version)
            raise WorkflowActionError("REAUTH_EXPIRED")

        challenge = await self.reauth_provider.start_challenge(
            user_id=user_id,
            workflow_id=workflow_id,
            approval_id=approval.approval_id,
        )
        now = _as_utc(self.clock())
        reauth = await self.reauthentications.create(
            user_id=user_id,
            workflow_id=workflow_id,
            approval_id=approval.approval_id,
            method=challenge.method,
            provider_reference=challenge.provider_reference,
            expires_at=now + self.reauth_ttl,
        )
        assert state.authorization is not None
        state.authorization.reauth_id = reauth.reauth_id
        state.authorization.reauth_expires_at = reauth.expires_at
        state.authorization.reauth_verified_at = None
        updated = await self.workflows.update_if_version(
            workflow_id=workflow_id,
            user_id=user_id,
            expected_version=expected_version,
            status=WorkflowStatus.REAUTH_REQUIRED,
            state=state.model_dump(mode="json"),
        )
        if updated is None:
            await self.session.rollback()
            raise WorkflowVersionConflictError
        await self._persist_authorization_event(
            updated,
            "reauth.challenge.created",
            reauth_id=reauth.reauth_id,
            status=reauth.status.value,
            expires_at=reauth.expires_at,
        )
        await self.publisher.persist(
            event_type="workflow.updated",
            conversation_id=model.conversation_id,
            task_id=model.source_task_id,
            data=self._event_data(updated),
        )
        await self.session.commit()
        return await self._to_workflow(updated)

    async def verify_reauthentication(
        self,
        workflow_id: UUID,
        *,
        user_id: str,
        reauth_id: UUID,
        verification_code: str,
        expected_version: int,
    ) -> Workflow:
        model, state = await self._load_action(workflow_id, user_id, expected_version)
        if model.status is not WorkflowStatus.REAUTH_REQUIRED:
            raise WorkflowActionError("WORKFLOW_NOT_REAUTH_REQUIRED")
        approval = await self._require_current_approval(model, state)
        reauth = await self.reauthentications.get_for_workflow_user(reauth_id, workflow_id, user_id)
        if reauth is None:
            raise WorkflowActionError("REAUTH_NOT_FOUND")
        if state.authorization is None or state.authorization.reauth_id != reauth.reauth_id:
            raise WorkflowActionError("REAUTH_NOT_CURRENT")
        if reauth.approval_id != approval.approval_id:
            raise WorkflowActionError("REAUTH_APPROVAL_MISMATCH")
        if reauth.status is not ReauthenticationStatus.PENDING:
            raise WorkflowActionError("REAUTH_NOT_PENDING")
        if _as_utc(reauth.expires_at) <= _as_utc(self.clock()):
            await self._expire_reauthentication(model, state, reauth, expected_version)
            raise WorkflowActionError("REAUTH_EXPIRED")

        verified = await self.reauth_provider.verify(
            user_id=user_id,
            workflow_id=workflow_id,
            approval_id=approval.approval_id,
            provider_reference=reauth.provider_reference,
            verification_code=verification_code,
        )
        if not verified:
            await self._record_failed_reauthentication(model, state, reauth, expected_version)
            raise WorkflowActionError("REAUTH_FAILED")

        now = _as_utc(self.clock())
        reauth.status = ReauthenticationStatus.VERIFIED
        reauth.verified_at = now
        assert state.authorization is not None
        state.authorization.reauth_verified_at = now
        updated = await self.workflows.update_if_version(
            workflow_id=workflow_id,
            user_id=user_id,
            expected_version=expected_version,
            status=WorkflowStatus.READY_FOR_COMMIT,
            state=state.model_dump(mode="json"),
        )
        if updated is None:
            await self.session.rollback()
            raise WorkflowVersionConflictError
        await self._persist_authorization_event(
            updated,
            "reauth.verified",
            reauth_id=reauth.reauth_id,
            status=reauth.status.value,
            expires_at=reauth.expires_at,
        )
        await self.publisher.persist(
            event_type="workflow.ready_for_commit",
            conversation_id=model.conversation_id,
            task_id=model.source_task_id,
            data=self._event_data(updated),
        )
        await self.session.commit()
        return await self._to_workflow(updated)

    async def cancel(self, workflow_id: UUID, *, user_id: str, expected_version: int) -> Workflow:
        model, state = await self._load_action(workflow_id, user_id, expected_version)
        if model.status not in {
            WorkflowStatus.WAITING_FOR_INPUT,
            WorkflowStatus.READY_FOR_REVIEW,
            WorkflowStatus.REAUTH_REQUIRED,
            WorkflowStatus.READY_FOR_COMMIT,
        }:
            raise WorkflowActionError("WORKFLOW_CANNOT_BE_CANCELLED")
        now = _as_utc(self.clock())
        await self._invalidate_authorization(model, now)
        state.authorization = None
        updated = await self.workflows.update_if_version(
            workflow_id=model.workflow_id,
            user_id=user_id,
            expected_version=expected_version,
            status=WorkflowStatus.CANCELLED,
            state=state.model_dump(mode="json"),
        )
        if updated is None:
            await self.session.rollback()
            raise WorkflowVersionConflictError
        await self.publisher.persist(
            event_type="workflow.cancelled",
            conversation_id=model.conversation_id,
            task_id=model.source_task_id,
            data=self._event_data(updated),
        )
        await self.session.commit()
        return await self._to_workflow(updated)

    async def _mutate_and_advance(
        self,
        model: WorkflowModel,
        state: TransferWorkflowState,
        expected_version: int,
    ) -> Workflow:
        await self._invalidate_authorization(model, _as_utc(self.clock()))
        state.authorization = None
        state.risk_decision = None
        status, advanced = await self.engine.advance(
            state, principal=ExecutionPrincipal.for_workflow(model.user_id)
        )
        if status is WorkflowStatus.READY_FOR_REVIEW:
            await self._evaluate_transfer_risk(advanced, user_id=model.user_id)
        updated = await self.workflows.update_if_version(
            workflow_id=model.workflow_id,
            user_id=model.user_id,
            expected_version=expected_version,
            status=status,
            state=advanced.model_dump(mode="json"),
        )
        if updated is None:
            await self.session.rollback()
            raise WorkflowVersionConflictError
        await self.publisher.persist(
            event_type=self._workflow_event_type(status),
            conversation_id=model.conversation_id,
            task_id=model.source_task_id,
            data=self._event_data(updated),
        )
        if advanced.risk_decision is not None:
            await self._persist_risk_event(updated, advanced.risk_decision, escalated=False)
        await self.session.commit()
        return await self._to_workflow(updated)

    async def _load_action(
        self, workflow_id: UUID, user_id: str, expected_version: int
    ) -> tuple[WorkflowModel, TransferWorkflowState]:
        model = await self.workflows.get_for_user(workflow_id, user_id)
        if model is None:
            raise WorkflowNotFoundError
        if model.version != expected_version:
            raise WorkflowVersionConflictError
        if model.status in {
            WorkflowStatus.CANCELLED,
            WorkflowStatus.FAILED,
            WorkflowStatus.COMMITTING,
            WorkflowStatus.SUCCEEDED,
        }:
            raise WorkflowActionError("WORKFLOW_NO_LONGER_ACCEPTS_ACTIONS")
        return model, TransferWorkflowState.model_validate(model.state_json)

    async def _require_current_approval(
        self, model: WorkflowModel, state: TransferWorkflowState
    ) -> ApprovalModel:
        authorization = state.authorization
        if authorization is None or state.review_payload is None:
            raise WorkflowActionError("APPROVAL_NOT_FOUND")
        approval = await self.approvals.get_for_workflow_user(
            authorization.approval_id, model.workflow_id, model.user_id
        )
        if approval is None or approval.status is not ApprovalStatus.APPROVED:
            raise WorkflowActionError("APPROVAL_NOT_VALID")
        if _as_utc(approval.expires_at) <= _as_utc(self.clock()):
            await self._expire_approval(model, state, approval)
            raise WorkflowActionError("APPROVAL_EXPIRED")
        current_hash = transfer_payload_hash(state.review_payload)
        if (
            approval.payload_hash != current_hash
            or authorization.approval_payload_hash != current_hash
        ):
            raise WorkflowActionError("APPROVAL_PAYLOAD_MISMATCH")
        return approval

    async def _invalidate_authorization(self, model: WorkflowModel, now: datetime) -> None:
        approvals = await self.approvals.invalidate_active(model.workflow_id, model.user_id, now)
        reauthentications = await self.reauthentications.invalidate_active(
            model.workflow_id, model.user_id, now
        )
        for approval in approvals:
            await self._persist_authorization_event(
                model,
                "approval.invalidated",
                approval_id=approval.approval_id,
                status=approval.status.value,
            )
        for reauth in reauthentications:
            await self._persist_authorization_event(
                model,
                "reauth.invalidated",
                reauth_id=reauth.reauth_id,
                status=reauth.status.value,
            )

    async def _expire_approval(
        self,
        model: WorkflowModel,
        state: TransferWorkflowState,
        approval: ApprovalModel,
    ) -> None:
        approval.status = ApprovalStatus.EXPIRED
        reauths = await self.reauthentications.invalidate_active(
            model.workflow_id, model.user_id, _as_utc(self.clock())
        )
        state.authorization = None
        updated = await self.workflows.update_if_version(
            workflow_id=model.workflow_id,
            user_id=model.user_id,
            expected_version=model.version,
            status=WorkflowStatus.READY_FOR_REVIEW,
            state=state.model_dump(mode="json"),
        )
        if updated is None:
            await self.session.rollback()
            raise WorkflowVersionConflictError
        await self._persist_authorization_event(
            updated,
            "approval.expired",
            approval_id=approval.approval_id,
            status=approval.status.value,
            expires_at=approval.expires_at,
        )
        for reauth in reauths:
            await self._persist_authorization_event(
                updated,
                "reauth.invalidated",
                reauth_id=reauth.reauth_id,
                status=reauth.status.value,
            )
        await self.publisher.persist(
            event_type="workflow.ready_for_review",
            conversation_id=model.conversation_id,
            task_id=model.source_task_id,
            data=self._event_data(updated),
        )
        await self.session.commit()

    async def _expire_reauthentication(
        self,
        model: WorkflowModel,
        state: TransferWorkflowState,
        reauth: ReauthenticationModel,
        expected_version: int,
    ) -> None:
        reauth.status = ReauthenticationStatus.EXPIRED
        assert state.authorization is not None
        state.authorization.reauth_id = None
        state.authorization.reauth_expires_at = None
        state.authorization.reauth_verified_at = None
        updated = await self.workflows.update_if_version(
            workflow_id=model.workflow_id,
            user_id=model.user_id,
            expected_version=expected_version,
            status=WorkflowStatus.REAUTH_REQUIRED,
            state=state.model_dump(mode="json"),
        )
        if updated is None:
            await self.session.rollback()
            raise WorkflowVersionConflictError
        await self._persist_authorization_event(
            updated,
            "reauth.expired",
            reauth_id=reauth.reauth_id,
            status=reauth.status.value,
            expires_at=reauth.expires_at,
        )
        await self.publisher.persist(
            event_type="workflow.reauth_required",
            conversation_id=model.conversation_id,
            task_id=model.source_task_id,
            data=self._event_data(updated),
        )
        await self.session.commit()

    async def _record_failed_reauthentication(
        self,
        model: WorkflowModel,
        state: TransferWorkflowState,
        reauth: ReauthenticationModel,
        expected_version: int,
    ) -> None:
        reauth.attempt_count += 1
        if reauth.attempt_count >= self.reauth_max_attempts:
            reauth.status = ReauthenticationStatus.FAILED
            assert state.authorization is not None
            state.authorization.reauth_id = None
            state.authorization.reauth_expires_at = None
            state.authorization.reauth_verified_at = None
        updated = await self.workflows.update_if_version(
            workflow_id=model.workflow_id,
            user_id=model.user_id,
            expected_version=expected_version,
            status=WorkflowStatus.REAUTH_REQUIRED,
            state=state.model_dump(mode="json"),
        )
        if updated is None:
            await self.session.rollback()
            raise WorkflowVersionConflictError
        await self._persist_authorization_event(
            updated,
            "reauth.failed",
            reauth_id=reauth.reauth_id,
            status=reauth.status.value,
        )
        await self.publisher.persist(
            event_type="workflow.reauth_required",
            conversation_id=model.conversation_id,
            task_id=model.source_task_id,
            data=self._event_data(updated),
        )
        await self.session.commit()

    async def _to_workflow(self, model: WorkflowModel) -> Workflow:
        state = TransferWorkflowState.model_validate(model.state_json)
        approval = await self.approvals.latest_for_workflow(model.workflow_id, model.user_id)
        reauth = await self.reauthentications.latest_for_workflow(model.workflow_id, model.user_id)
        operation = await self.operations.get_for_workflow(model.workflow_id, model.user_id)
        return Workflow(
            workflow_id=model.workflow_id,
            user_id=model.user_id,
            conversation_id=model.conversation_id,
            source_task_id=model.source_task_id,
            workflow_type=model.workflow_type,
            status=model.status,
            version=model.version,
            state=model.state_json,
            risk_level=(state.risk_decision.level if state.risk_decision is not None else None),
            risk_decision=state.risk_decision,
            approval_summary=(
                ApprovalSummary(
                    approval_id=approval.approval_id,
                    status=approval.status,
                    expires_at=approval.expires_at,
                )
                if approval is not None
                else None
            ),
            reauth_summary=(
                ReauthenticationSummary(
                    reauth_id=reauth.reauth_id,
                    status=reauth.status,
                    method=reauth.method,
                    expires_at=reauth.expires_at,
                )
                if reauth is not None
                else None
            ),
            operation_summary=(
                OperationSummary(
                    operation_id=operation.operation_id,
                    status=operation.status,
                    provider_reference=operation.provider_reference,
                    error_code=operation.error_code,
                    created_at=operation.created_at,
                    completed_at=operation.completed_at,
                )
                if operation is not None
                else None
            ),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    async def _evaluate_transfer_risk(
        self,
        state: TransferWorkflowState,
        *,
        user_id: str,
    ) -> TransferRiskDecision:
        if state.review_payload is None:
            raise WorkflowActionError("TRANSFER_RISK_FACTS_MISSING")
        evaluated_at = _as_utc(self.clock())
        facts = await self.risk_facts.for_user(
            user_id=user_id,
            currency=state.review_payload.currency,
            evaluated_at=evaluated_at,
        )
        fresh = self.risk_policy.evaluate(
            requested_amount=state.review_payload.amount,
            currency=state.review_payload.currency,
            business_date=facts.business_date,
            successful_transfer_total_today=facts.successful_total,
            in_flight_transfer_exposure_today=facts.in_flight_exposure,
            evaluated_at=evaluated_at,
        )
        decision = self.risk_policy.retain_stricter(state.risk_decision, fresh)
        state.risk_decision = decision
        return decision

    async def _persist_risk_event(
        self,
        model: WorkflowModel,
        decision: TransferRiskDecision,
        *,
        escalated: bool,
    ):  # type: ignore[no-untyped-def]
        data = decision.model_dump(mode="json")
        data["workflow_id"] = str(model.workflow_id)
        data["version"] = model.version
        return await self.publisher.persist(
            event_type=("workflow.risk_escalated" if escalated else "workflow.risk_evaluated"),
            conversation_id=model.conversation_id,
            task_id=model.source_task_id,
            data=data,
        )

    async def _persist_authorization_event(
        self,
        model: WorkflowModel,
        event_type: str,
        *,
        approval_id: UUID | None = None,
        reauth_id: UUID | None = None,
        status: str,
        expires_at: datetime | None = None,
    ):  # type: ignore[no-untyped-def]
        data: dict[str, object] = {
            "workflow_id": str(model.workflow_id),
            "status": status,
            "version": model.version,
        }
        if approval_id is not None:
            data["approval_id"] = str(approval_id)
        if reauth_id is not None:
            data["reauth_id"] = str(reauth_id)
        if expires_at is not None:
            data["expires_at"] = expires_at.isoformat()
        return await self.publisher.persist(
            event_type=event_type,
            conversation_id=model.conversation_id,
            task_id=model.source_task_id,
            data=data,
        )

    @staticmethod
    def _is_review_or_authorization(status: WorkflowStatus) -> bool:
        return status in {
            WorkflowStatus.READY_FOR_REVIEW,
            WorkflowStatus.REAUTH_REQUIRED,
            WorkflowStatus.READY_FOR_COMMIT,
        }

    @staticmethod
    def _workflow_event_type(status: WorkflowStatus) -> str:
        return {
            WorkflowStatus.WAITING_FOR_INPUT: "workflow.waiting_for_input",
            WorkflowStatus.READY_FOR_REVIEW: "workflow.ready_for_review",
            WorkflowStatus.REAUTH_REQUIRED: "workflow.reauth_required",
            WorkflowStatus.READY_FOR_COMMIT: "workflow.ready_for_commit",
            WorkflowStatus.COMMITTING: "workflow.committing",
            WorkflowStatus.SUCCEEDED: "workflow.succeeded",
            WorkflowStatus.FAILED: "workflow.failed",
            WorkflowStatus.CANCELLED: "workflow.cancelled",
        }.get(status, "workflow.updated")

    @staticmethod
    def _event_data(model: WorkflowModel) -> dict[str, object]:
        data: dict[str, object] = {
            "workflow_id": str(model.workflow_id),
            "workflow_type": model.workflow_type.value,
            "status": model.status.value,
            "version": model.version,
        }
        required = model.state_json.get("required_input")
        if isinstance(required, dict) and required.get("type"):
            data["required_input_type"] = required["type"]
        return data
