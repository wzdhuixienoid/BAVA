from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from banking_api.api.dependencies import (
    EventBusDependency,
    PrincipalDependency,
    SessionDependency,
    TransferWorkflowEngineDependency,
)
from banking_api.application.operation_service import (
    OperationActionError,
    OperationLeaseLostError,
    OperationNotFoundError,
    OperationService,
    OperationVersionConflictError,
)
from banking_api.application.workflow_service import (
    WorkflowActionError,
    WorkflowNotFoundError,
    WorkflowService,
    WorkflowVersionConflictError,
)
from banking_api.domain.workflow import Workflow
from banking_api.workflows.transfer.models import (
    ApproveTransferAction,
    CancelWorkflowAction,
    CommitTransferAction,
    SelectPayeeAction,
    SelectSourceAccountAction,
    SetAmountAction,
    SetRecipientQueryAction,
    StartReauthenticationAction,
    VerifyReauthenticationAction,
)

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _service(session, bus, engine) -> WorkflowService:  # type: ignore[no-untyped-def]
    return WorkflowService(session, bus, engine)


def _raise_action_error(exc: Exception) -> NoReturn:
    if isinstance(exc, (WorkflowNotFoundError, OperationNotFoundError)):
        raise HTTPException(status_code=404, detail="未找到该工作流") from exc
    if isinstance(
        exc,
        (
            WorkflowVersionConflictError,
            OperationVersionConflictError,
            OperationLeaseLostError,
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="工作流已更新，请刷新后重试",
        ) from exc
    raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", response_model=list[Workflow])
async def list_workflows(
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
    engine: TransferWorkflowEngineDependency,
    conversation_id: Annotated[UUID | None, Query()] = None,
) -> list[Workflow]:
    return await _service(session, bus, engine).list(
        user_id=principal.user_id, conversation_id=conversation_id
    )


@router.get("/{workflow_id}", response_model=Workflow)
async def get_workflow(
    workflow_id: UUID,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
    engine: TransferWorkflowEngineDependency,
) -> Workflow:
    try:
        return await _service(session, bus, engine).get(workflow_id, user_id=principal.user_id)
    except WorkflowNotFoundError as exc:
        _raise_action_error(exc)


@router.post("/{workflow_id}/actions/select-payee", response_model=Workflow)
async def select_payee(
    workflow_id: UUID,
    body: SelectPayeeAction,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
    engine: TransferWorkflowEngineDependency,
) -> Workflow:
    try:
        return await _service(session, bus, engine).select_payee(
            workflow_id,
            user_id=principal.user_id,
            payee_id=body.payee_id,
            expected_version=body.expected_version,
        )
    except (WorkflowNotFoundError, WorkflowVersionConflictError, WorkflowActionError) as exc:
        _raise_action_error(exc)


@router.post("/{workflow_id}/actions/set-recipient-query", response_model=Workflow)
async def set_recipient_query(
    workflow_id: UUID,
    body: SetRecipientQueryAction,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
    engine: TransferWorkflowEngineDependency,
) -> Workflow:
    try:
        return await _service(session, bus, engine).set_recipient_query(
            workflow_id,
            user_id=principal.user_id,
            recipient_query=body.recipient_query,
            expected_version=body.expected_version,
        )
    except (WorkflowNotFoundError, WorkflowVersionConflictError, WorkflowActionError) as exc:
        _raise_action_error(exc)


@router.post("/{workflow_id}/actions/select-source-account", response_model=Workflow)
async def select_source_account(
    workflow_id: UUID,
    body: SelectSourceAccountAction,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
    engine: TransferWorkflowEngineDependency,
) -> Workflow:
    try:
        return await _service(session, bus, engine).select_source_account(
            workflow_id,
            user_id=principal.user_id,
            account_id=body.account_id,
            expected_version=body.expected_version,
        )
    except (WorkflowNotFoundError, WorkflowVersionConflictError, WorkflowActionError) as exc:
        _raise_action_error(exc)


@router.post("/{workflow_id}/actions/set-amount", response_model=Workflow)
async def set_amount(
    workflow_id: UUID,
    body: SetAmountAction,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
    engine: TransferWorkflowEngineDependency,
) -> Workflow:
    try:
        return await _service(session, bus, engine).set_amount(
            workflow_id,
            user_id=principal.user_id,
            amount=body.amount,
            expected_version=body.expected_version,
        )
    except (WorkflowNotFoundError, WorkflowVersionConflictError, WorkflowActionError) as exc:
        _raise_action_error(exc)


@router.post("/{workflow_id}/actions/cancel", response_model=Workflow)
async def cancel_workflow(
    workflow_id: UUID,
    body: CancelWorkflowAction,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
    engine: TransferWorkflowEngineDependency,
) -> Workflow:
    try:
        return await _service(session, bus, engine).cancel(
            workflow_id,
            user_id=principal.user_id,
            expected_version=body.expected_version,
        )
    except (WorkflowNotFoundError, WorkflowVersionConflictError, WorkflowActionError) as exc:
        _raise_action_error(exc)


@router.post("/{workflow_id}/actions/approve", response_model=Workflow)
async def approve_transfer(
    workflow_id: UUID,
    body: ApproveTransferAction,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
    engine: TransferWorkflowEngineDependency,
) -> Workflow:
    try:
        return await _service(session, bus, engine).approve(
            workflow_id,
            user_id=principal.user_id,
            expected_version=body.expected_version,
        )
    except (WorkflowNotFoundError, WorkflowVersionConflictError, WorkflowActionError) as exc:
        _raise_action_error(exc)


@router.post("/{workflow_id}/actions/start-reauth", response_model=Workflow)
async def start_reauthentication(
    workflow_id: UUID,
    body: StartReauthenticationAction,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
    engine: TransferWorkflowEngineDependency,
) -> Workflow:
    try:
        return await _service(session, bus, engine).start_reauthentication(
            workflow_id,
            user_id=principal.user_id,
            expected_version=body.expected_version,
        )
    except (WorkflowNotFoundError, WorkflowVersionConflictError, WorkflowActionError) as exc:
        _raise_action_error(exc)


@router.post("/{workflow_id}/actions/verify-reauth", response_model=Workflow)
async def verify_reauthentication(
    workflow_id: UUID,
    body: VerifyReauthenticationAction,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
    engine: TransferWorkflowEngineDependency,
) -> Workflow:
    try:
        return await _service(session, bus, engine).verify_reauthentication(
            workflow_id,
            user_id=principal.user_id,
            reauth_id=body.reauth_id,
            verification_code=body.verification_code,
            expected_version=body.expected_version,
        )
    except (WorkflowNotFoundError, WorkflowVersionConflictError, WorkflowActionError) as exc:
        _raise_action_error(exc)


@router.post("/{workflow_id}/actions/commit", response_model=Workflow)
async def commit_transfer(
    workflow_id: UUID,
    body: CommitTransferAction,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
    engine: TransferWorkflowEngineDependency,
) -> Workflow:
    try:
        await OperationService(session, bus, engine).commit_workflow(
            workflow_id,
            user_id=principal.user_id,
            expected_version=body.expected_version,
        )
        return await _service(session, bus, engine).get(
            workflow_id, user_id=principal.user_id
        )
    except (
        OperationNotFoundError,
        OperationVersionConflictError,
        OperationLeaseLostError,
        OperationActionError,
    ) as exc:
        _raise_action_error(exc)
