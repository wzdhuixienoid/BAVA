from pydantic import BaseModel

from banking_api.domain.enums import PolicyDecision, RiskLevel
from banking_api.tools.models import ToolSpec


class PolicyResult(BaseModel):
    decision: PolicyDecision
    reason: str


class PolicyService:
    """Read-only minimal-agent allow rule; every unmatched request is denied."""

    def evaluate(
        self,
        *,
        spec: ToolSpec | None,
        caller: str,
        authenticated: bool,
        agent_allowlist: frozenset[str],
    ) -> PolicyResult:
        allowed = (
            authenticated
            and spec is not None
            and caller in spec.allowed_callers
            and spec.capability_id in agent_allowlist
            and spec.risk_level is RiskLevel.R1_PRIVATE_READ
            and not spec.side_effect
        )
        if allowed:
            return PolicyResult(
                decision=PolicyDecision.ALLOW, reason="read-only capability allowed"
            )
        return PolicyResult(
            decision=PolicyDecision.DENY,
            reason=(
                "default deny: caller, authentication, registration, risk, "
                "or allowlist mismatch"
            ),
        )
