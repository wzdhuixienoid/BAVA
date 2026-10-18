"""Explicit action evidence for page actions that have no conversation Task."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from banking_api.persistence.models import DomainActionAuditModel


class DomainActionAudit(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    trace_id: UUID
    action: str
    resource_id: str
    idempotency_key: UUID | None
    payload_hash: str
    outcome: str
    evidence: list[dict]
    created_at: datetime


def payload_digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


async def record_action(
    session,
    *,
    user_id: str,
    action: str,
    resource_id: str,
    payload: dict,
    outcome: str,
    evidence: list[dict],
    idempotency_key: UUID | None = None,
) -> DomainActionAuditModel:
    """Call within the business transaction. Payload is hashed, never retained verbatim."""
    now = datetime.now(UTC)
    row = DomainActionAuditModel(
        user_id=user_id,
        action=action,
        resource_id=resource_id,
        idempotency_key=idempotency_key,
        payload_hash=payload_digest(payload),
        outcome=outcome,
        evidence=[
            dict(item, timestamp=item.get("timestamp", now.isoformat())) for item in evidence
        ],
    )
    session.add(row)
    await session.flush()
    return row
