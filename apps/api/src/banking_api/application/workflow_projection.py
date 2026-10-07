"""Read-only projection of existing Workflow/Approval/Operation facts."""

from decimal import Decimal

from banking_api.domain.enums import OperationStatus, WorkflowStatus
from banking_api.domain.workflow_presentation import (
    TransferAccountOption,
    WorkflowPresentation,
    WorkflowStage,
    WorkflowStageStatus,
)
from banking_api.financial.report_formatter import ReportFormatter
from banking_api.tools.models import PayeeSummary


def workflow_presentation(*, status, transfer, subscription, approval, reauth, operation):
    """No mutation, authorization, risk evaluation or Provider I/O occurs here."""
    done = WorkflowStageStatus.COMPLETED
    pending = WorkflowStageStatus.PENDING
    waiting = WorkflowStageStatus.WAITING_USER
    success = status is WorkflowStatus.SUCCEEDED and (
        operation is not None and operation.status is OperationStatus.SUCCEEDED
    )
    review = transfer.review_payload if transfer else subscription.review_payload
    risk = transfer.risk_decision if transfer else None
    approval_required = risk.required_approval if risk else True if subscription else None
    reauth_required = (
        risk.required_reauthentication
        if risk
        else subscription.draft.action == "SUBSCRIPTION_RESUME"
        if subscription
        else None
    )
    approval_status = (
        done
        if approval and approval.status.value in {"APPROVED", "CONSUMED"}
        else (
            WorkflowStageStatus(approval.status.value)
            if approval and approval.status.value != "PENDING"
            else waiting
            if status is WorkflowStatus.READY_FOR_REVIEW
            else pending
        )
    )
    reauth_status = (
        WorkflowStageStatus.SKIPPED
        if reauth_required is False
        else done
        if reauth and reauth.status.value == "VERIFIED"
        else WorkflowStageStatus(reauth.status.value)
        if reauth and reauth.status.value != "PENDING"
        else waiting
        if status is WorkflowStatus.REAUTH_REQUIRED
        else pending
    )
    provider_status = (
        done
        if operation and operation.status is OperationStatus.SUCCEEDED
        else WorkflowStageStatus.FAILED
        if operation and operation.status is OperationStatus.FAILED
        else WorkflowStageStatus.UNKNOWN
        if operation and operation.status is OperationStatus.UNKNOWN
        else WorkflowStageStatus.RUNNING
        if operation
        else pending
    )
    stages = [("intent", "需求解析", done)]
    if transfer:
        required = transfer.required_input.type.value if transfer.required_input else None
        stages += [
            (
                "payee",
                "收款人确认",
                done
                if transfer.draft.payee_id
                else waiting
                if required in {"RECIPIENT_QUERY", "PAYEE_SELECTION"}
                else pending,
            ),
            (
                "account",
                "付款账户确认",
                done
                if transfer.draft.source_account_id
                else waiting
                if required == "SOURCE_ACCOUNT_SELECTION"
                else pending,
            ),
            (
                "validation",
                "金额与余额校验",
                done
                if transfer.validation and transfer.validation.is_valid
                else WorkflowStageStatus.FAILED
                if transfer.validation
                else waiting
                if required == "AMOUNT"
                else pending,
            ),
            ("risk", "风险评估", done if risk else pending),
        ]
    else:
        stages += [
            (
                "subscription",
                "订阅确认",
                done if review else waiting if subscription.required_input else pending,
            )
        ]
    stages += [
        ("approval", "用户确认", approval_status),
        ("reauth", "强身份验证", reauth_status),
        (
            "submit",
            "提交执行",
            done
            if operation
            else waiting
            if status is WorkflowStatus.READY_FOR_COMMIT
            else pending,
        ),
        ("provider", "Provider 处理", provider_status),
        (
            "final",
            "最终结果",
            done
            if success
            else WorkflowStageStatus.FAILED
            if status is WorkflowStatus.FAILED
            else WorkflowStageStatus.CANCELLED
            if status is WorkflowStatus.CANCELLED
            else pending,
        ),
    ]
    formatter = ReportFormatter()
    return WorkflowPresentation(
        business_success=success,
        approval_required=approval_required,
        reauthentication_required=reauth_required,
        amount_display=formatter.money(review.amount, review.currency) if review else None,
        transfer_state=transfer,
        subscription_state=subscription,
        account_options=[
            TransferAccountOption(
                account_id=item["account_id"],
                display_name=item["display_name"],
                masked_number=item["masked_number"],
                currency=item["currency"],
                available_balance_display=formatter.money(
                    Decimal(item["available_balance"]), item["currency"]
                ),
            )
            for item in transfer.source_account_options
        ]
        if transfer
        else [],
        payee_options=[PayeeSummary.model_validate(item) for item in transfer.payee_options]
        if transfer
        else [],
        stages=[
            WorkflowStage(key=key, label=label, status=stage_status)
            for key, label, stage_status in stages
        ],
    )
