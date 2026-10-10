"""Wealth branch of existing OperationRecoveryWorker, preserving its lease fencing."""

from datetime import datetime

from banking_api.application.operation_service import OperationLeaseLostError
from banking_api.domain.enums import OperationStatus, TaskStatus, WorkflowStatus
from banking_api.domain.principal import ExecutionPrincipal
from banking_api.persistence.models import TaskModel
from banking_api.wealth.calculation import utc


async def reconcile_wealth(service, operation, lease_owner):
    engine = service.engine.wealth_engine
    principal = ExecutionPrincipal.for_recovery(operation.user_id)
    await service.session.commit()
    if operation.status == OperationStatus.CREATED:
        output = await engine.execute(operation, principal, False)
        if output["outcome"] == "UNKNOWN":
            status = OperationStatus.UNKNOWN
        elif output["outcome"] == "FAILED":
            status = OperationStatus.FAILED
        else:
            status = OperationStatus.SUBMITTED
    else:
        output = await engine.execute(operation, principal, True)
        status = {
            "PENDING": OperationStatus.SUBMITTED,
            "SUCCEEDED": OperationStatus.SUCCEEDED,
            "FAILED": OperationStatus.FAILED,
        }.get(output["status"], OperationStatus.UNKNOWN)
    now = utc(service.clock())
    # Security -> Workflow -> Operation; provider transactions have already ended.
    from banking_api.security.guard import acquire_security_user_lock

    await acquire_security_user_lock(service.session, operation.user_id)
    workflow = await service.workflows.get_for_user_for_update(
        operation.workflow_id, operation.user_id
    )
    op = await service.operations.get_claimed(
        operation.operation_id, lease_owner, lease_valid_at=now, for_update=True
    )
    if op is None or op.version != operation.version:
        await service.session.rollback()
        raise OperationLeaseLostError
    terminal = status in {OperationStatus.SUCCEEDED, OperationStatus.FAILED}
    normal_wait = status == OperationStatus.SUBMITTED and output.get("next_reconcile_at")
    if terminal:
        next_time = None
    elif normal_wait:
        next_time = (
            datetime.fromisoformat(output["next_reconcile_at"])
            if isinstance(output["next_reconcile_at"], str)
            else output["next_reconcile_at"]
        )
    else:
        op.reconcile_attempts += 1
        next_time = now + service.recovery_policy.retry_delay(op.reconcile_attempts)
    op.status, op.next_reconcile_at = status, next_time
    op.provider_reference = output.get("provider_reference") or op.provider_reference
    op.error_code = output.get("error_code")
    op.version += 1
    op.last_reconcile_at = now
    op.lease_owner = op.lease_expires_at = None
    if status == OperationStatus.SUBMITTED and not op.submitted_at:
        op.submitted_at = now
    if terminal:
        op.completed_at = now
    workflow.status = (
        WorkflowStatus.SUCCEEDED
        if status == OperationStatus.SUCCEEDED
        else WorkflowStatus.FAILED
        if status == OperationStatus.FAILED
        else WorkflowStatus.COMMITTING
    )
    if status == OperationStatus.FAILED:
        from banking_api.wealth.order_explanation import ERRORS

        reason, next_step = ERRORS.get(op.error_code, ("订单明确失败", "查看处理过程及审计"))
        workflow.state_json = {
            **workflow.state_json,
            "validation_message": reason + "；" + next_step,
        }
    workflow.version += 1
    task = await service.session.get(TaskModel, workflow.source_task_id)
    task.status = TaskStatus.COMPLETED if terminal else TaskStatus.WAITING_EXTERNAL
    task.version += 1
    await service._operation_event(op, f"operation.{status.value.lower()}")
    stage = (
        "succeeded"
        if status == OperationStatus.SUCCEEDED
        else "failed"
        if terminal
        else "committing"
    )
    await service.publisher.persist(
        event_type=f"workflow.{stage}",
        conversation_id=workflow.conversation_id,
        task_id=workflow.source_task_id,
        data={
            "workflow_id": str(workflow.workflow_id),
            "status": workflow.status.value,
            "version": workflow.version,
        },
    )
    await service.session.commit()
    return service._resource(op)
