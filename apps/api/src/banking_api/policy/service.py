from typing import Any

from pydantic import BaseModel

from banking_api.domain.enums import PolicyDecision


class PolicyResult(BaseModel):
    decision: PolicyDecision
    reason: str


class PolicyService:
    """Iteration 0 defaults unknown capabilities to DENY."""

    def evaluate(self, capability_id: str, context: dict[str, Any] | None = None) -> PolicyResult:
        del context
        return PolicyResult(
            decision=PolicyDecision.DENY,
            reason=f"Capability is not allowed in bootstrap iteration: {capability_id}",
        )

