"""Durable authority checks for workflow tools; consumed grants survive recovery TTLs."""

import hashlib
import json

from sqlalchemy import select

from banking_api.domain.enums import ApprovalStatus
from banking_api.domain.operation import OperationType
from banking_api.persistence.models import ApprovalModel, OperationModel


async def authorized_operation(session, operation_id, user_id, operation_types):
    operation = await session.scalar(
        select(OperationModel).where(
            OperationModel.operation_id == operation_id,
            OperationModel.user_id == user_id,
            OperationModel.operation_type.in_(operation_types),
        )
    )
    if operation is None:
        return None
    approval = await session.get(ApprovalModel, operation.approval_id)
    if (
        approval is None
        or approval.user_id != user_id
        or approval.workflow_id != operation.workflow_id
        or approval.status != ApprovalStatus.CONSUMED
        or approval.consumed_by_operation_id != operation.operation_id
        or approval.payload_hash != operation.payload_hash
    ):
        return None
    # Each family preserves the canonical encoding used when its grant was consumed.
    options = (
        {}
        if operation.operation_type
        in {
            OperationType.WEALTH_PURCHASE,
            OperationType.WEALTH_REDEEM,
        }
        else {"separators": (",", ":")}
    )
    digest = hashlib.sha256(
        json.dumps(
            operation.payload_json,
            ensure_ascii=False,
            sort_keys=True,
            **options,
        ).encode()
    ).hexdigest()
    return operation if digest == operation.payload_hash else None
