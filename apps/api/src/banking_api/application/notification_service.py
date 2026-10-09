"""Create one durable result notification per scheduled occurrence, in its transaction."""

from sqlalchemy import select

from banking_api.persistence.models import NotificationModel
from banking_api.workflows.transfer.models import TransferWorkflowState


async def notify_schedule_result(session, scheduled, workflow, status, now):
    key = f"schedule:{scheduled.schedule_id}:result"
    if await session.scalar(select(NotificationModel).where(NotificationModel.source_key == key)):
        return
    state = TransferWorkflowState.model_validate(workflow.state_json)
    review = state.review_payload
    recipient = review.payee_display_name if review else state.draft.recipient_query or "收款人"
    amount = review.amount if review else state.draft.amount
    currency = review.currency if review else state.draft.currency
    label = {"SUCCEEDED": "执行成功", "FAILED": "执行失败", "EXPIRED": "已过期未执行"}[status]
    kind = "周期转账" if scheduled.series_id else "预约转账"
    period = f"第 {scheduled.occurrence_index} 期，" if scheduled.series_id else ""
    money = f"{amount:.2f} {currency}" if amount is not None else "金额待确认"
    session.add(
        NotificationModel(
            user_id=scheduled.user_id,
            source_key=key,
            title=f"{kind}{label}",
            message=f"{period}给{recipient}转账 {money}，{label}。请在预约与周期转账中查看详情。",
            schedule_id=scheduled.schedule_id,
            created_at=now,
        )
    )
