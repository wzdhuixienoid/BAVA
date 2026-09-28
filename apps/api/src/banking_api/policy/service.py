from pydantic import BaseModel

from banking_api.domain.enums import PolicyDecision, RiskLevel
from banking_api.domain.risk import BusinessRiskLevel
from banking_api.tools.models import ToolSpec


class PolicyResult(BaseModel):
    decision: PolicyDecision
    reason: str
    business_risk_level: BusinessRiskLevel | None = None


class PolicyService:
    """Default-deny capability policy including the explicit transfer commit boundary."""

    def evaluate(
        self,
        *,
        spec: ToolSpec | None,
        caller: str,
        authenticated: bool,
        agent_allowlist: frozenset[str],
    ) -> PolicyResult:
        common = (
            authenticated
            and spec is not None
            and caller in spec.allowed_callers
            and spec.capability_id in agent_allowlist
        )
        read_allowed = (
            common
            and spec is not None
            and spec.risk_level is RiskLevel.R1_PRIVATE_READ
            and not spec.side_effect
        )
        commit_allowed = (
            common
            and spec is not None
            and caller == "workflow:transfer"
            and spec.capability_id == "transfer.commit"
            and spec.risk_level is RiskLevel.R4_FINANCIAL_COMMIT
            and spec.side_effect
        )
        if read_allowed or commit_allowed:
            return PolicyResult(
                decision=PolicyDecision.ALLOW,
                reason=(
                    "transfer financial commit allowed"
                    if commit_allowed
                    else "read-only capability allowed"
                ),
                business_risk_level=(BusinessRiskLevel.GREEN if read_allowed else None),
            )
        return PolicyResult(
            decision=PolicyDecision.DENY,
            reason=(
                "default deny: caller, authentication, registration, risk, "
                "or allowlist mismatch"
            ),
        )
