from sqlalchemy import select

from banking_api.domain.approval import ApprovalSummary
from banking_api.domain.operation import OperationSummary
from banking_api.domain.reauthentication import ReauthenticationSummary
from banking_api.domain.risk import BusinessRiskLevel
from banking_api.domain.workflow import Workflow
from banking_api.domain.workflow_presentation import WorkflowPresentation, WorkflowStage
from banking_api.wealth.models import WealthOrder


async def wealth_workflow_resource(service, model):
    a = await service.approvals.latest_for_workflow(model.workflow_id, model.user_id)
    r = await service.reauthentications.latest_for_workflow(model.workflow_id, model.user_id)
    o = await service.operations.get_for_workflow(model.workflow_id, model.user_id)
    status = model.status.value
    order = (
        await service.session.scalar(
            select(WealthOrder).where(
                WealthOrder.operation_id == o.operation_id, WealthOrder.user_id == model.user_id
            )
        )
        if o
        else None
    )
    done = bool(
        status == "SUCCEEDED"
        and o
        and o.status.value == "SUCCEEDED"
        and order
        and order.status == "SETTLED"
    )
    review = model.state_json.get("review")
    return Workflow(
        workflow_id=model.workflow_id,
        user_id=model.user_id,
        conversation_id=model.conversation_id,
        source_task_id=model.source_task_id,
        workflow_type=model.workflow_type,
        status=model.status,
        version=model.version,
        state=model.state_json,
        risk_level=BusinessRiskLevel.RED,
        wealth_risk_decision=model.state_json.get("wealth_risk"),
        approval_summary=ApprovalSummary.model_validate(a, from_attributes=True) if a else None,
        reauth_summary=ReauthenticationSummary.model_validate(r, from_attributes=True)
        if r
        else None,
        operation_summary=OperationSummary.model_validate(o, from_attributes=True) if o else None,
        presentation=WorkflowPresentation(
            wealth_state=model.state_json,
            business_success=done,
            approval_required=True,
            reauthentication_required=True,
            amount_display=review["quantity_display"] if review else None,
            stages=[
                WorkflowStage(
                    key="review", label="核对交易", status="COMPLETED" if a else "WAITING_USER"
                ),
                WorkflowStage(
                    key="approval", label="用户确认", status="COMPLETED" if a else "PENDING"
                ),
                WorkflowStage(
                    key="reauth",
                    label="强验证",
                    status="COMPLETED"
                    if r and r.status.value == "VERIFIED"
                    else "WAITING_USER"
                    if a
                    else "PENDING",
                ),
                WorkflowStage(
                    key="settle",
                    label="成交及到账",
                    status="COMPLETED"
                    if done
                    else "FAILED"
                    if status == "FAILED"
                    else "RUNNING"
                    if status == "COMMITTING"
                    else "PENDING",
                ),
            ],
        ),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
