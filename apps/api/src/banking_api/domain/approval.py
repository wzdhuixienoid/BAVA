from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from banking_api.domain.enums import ApprovalStatus


class Approval(BaseModel):
    """Concept boundary only; hashing and approval execution are intentionally absent."""

    approval_id: UUID
    workflow_id: UUID
    payload_hash: str
    status: ApprovalStatus
    created_at: datetime
    expires_at: datetime
    approved_at: datetime | None = None

