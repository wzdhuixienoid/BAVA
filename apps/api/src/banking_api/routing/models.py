from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from banking_api.domain.enums import RequestedOutput


class RequestRoute(StrEnum):
    MINIMAL_BANKING = "MINIMAL_BANKING"
    FINANCIAL_ANALYSIS = "FINANCIAL_ANALYSIS"
    TRANSFER_WORKFLOW = "TRANSFER_WORKFLOW"
    SUBSCRIPTION_ANALYSIS = "SUBSCRIPTION_ANALYSIS"
    SUBSCRIPTION_CANCEL = "SUBSCRIPTION_CANCEL"
    COMPLEX_PLAN = "COMPLEX_PLAN"
    UNSUPPORTED = "UNSUPPORTED"


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: RequestRoute
    requested_output: RequestedOutput
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_output_for_route(self) -> "RouteDecision":
        if self.route in {RequestRoute.TRANSFER_WORKFLOW, RequestRoute.SUBSCRIPTION_CANCEL}:
            if self.requested_output is not RequestedOutput.WORKFLOW:
                raise ValueError("Workflow routes must request workflow output")
            return self
        if (
            self.route is not RequestRoute.FINANCIAL_ANALYSIS
            and self.requested_output is not RequestedOutput.ANSWER
        ):
            raise ValueError("Only financial analysis can request a monthly report")
        if self.requested_output is RequestedOutput.WORKFLOW:
            raise ValueError("Only workflow routes can request workflow output")
        return self
