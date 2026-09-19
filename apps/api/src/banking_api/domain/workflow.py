from uuid import UUID

from pydantic import BaseModel

from banking_api.domain.enums import WorkflowStatus


class Workflow(BaseModel):
    """Concept boundary only; Iteration 0 has no workflow persistence or execution."""

    workflow_id: UUID
    workflow_type: str
    status: WorkflowStatus
    version: int

