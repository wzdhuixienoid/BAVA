from uuid import UUID

from pydantic import BaseModel

from banking_api.domain.enums import OperationStatus


class Operation(BaseModel):
    """Concept boundary only; Iteration 0 performs no external operations."""

    operation_id: UUID
    workflow_id: UUID
    idempotency_key: str
    status: OperationStatus
    external_reference: str | None = None

