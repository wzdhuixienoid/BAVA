from dataclasses import dataclass
from types import MappingProxyType

from banking_api.planning.models import PlanCapability


@dataclass(frozen=True)
class PlanCapabilityDefinition:
    executor_id: str
    executor_kind: str

    @property
    def read_only(self) -> bool:
        return self.executor_kind == "AGENT"


class PlanCapabilityRegistry:
    """Static high-level capabilities; this registry never resolves tools."""

    definitions = MappingProxyType(
        {
            PlanCapability.ACCOUNT_QUERY: PlanCapabilityDefinition(
                "agent:minimal-banking", "AGENT"
            ),
            PlanCapability.FINANCIAL_ANALYSIS: PlanCapabilityDefinition(
                "agent:financial-analysis", "AGENT"
            ),
            PlanCapability.SUBSCRIPTION_ANALYSIS: PlanCapabilityDefinition(
                "agent:subscription-analysis", "AGENT"
            ),
            PlanCapability.TRANSFER_WORKFLOW: PlanCapabilityDefinition(
                "workflow:transfer", "WORKFLOW"
            ),
            PlanCapability.SUBSCRIPTION_CANCEL_WORKFLOW: PlanCapabilityDefinition(
                "workflow:subscription-cancel", "WORKFLOW"
            ),
        }
    )

    def get(self, capability: PlanCapability) -> PlanCapabilityDefinition:
        return self.definitions[capability]
