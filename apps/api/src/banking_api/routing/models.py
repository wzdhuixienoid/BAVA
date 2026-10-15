from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from banking_api.domain.enums import RequestedOutput


class RequestRoute(StrEnum):
    WEALTH_ANALYSIS = "WEALTH_ANALYSIS"
    WEALTH_PURCHASE = "WEALTH_PURCHASE"
    WEALTH_REDEEM = "WEALTH_REDEEM"
    ACCOUNT_QUERY = "ACCOUNT_QUERY"
    PERSONAL_BANKING = "PERSONAL_BANKING"
    FINANCIAL_ANALYSIS = "FINANCIAL_ANALYSIS"
    TRANSFER_WORKFLOW = "TRANSFER_WORKFLOW"
    AA_COLLECTION = "AA_COLLECTION"
    SUBSCRIPTION_ANALYSIS = "SUBSCRIPTION_ANALYSIS"
    SUBSCRIPTION_CANCEL = "SUBSCRIPTION_CANCEL"
    SUBSCRIPTION_RESUME = "SUBSCRIPTION_RESUME"
    COMPLEX_PLAN = "COMPLEX_PLAN"
    UNSUPPORTED = "UNSUPPORTED"


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: RequestRoute
    requested_output: RequestedOutput
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="before")
    @classmethod
    def legacy_account_route(cls, value):
        if isinstance(value, dict) and value.get("route") == "MINIMAL_BANKING":
            return {**value, "route": RequestRoute.ACCOUNT_QUERY}
        return value

    @model_validator(mode="after")
    def validate_output_for_route(self) -> "RouteDecision":
        if self.route in {
            RequestRoute.TRANSFER_WORKFLOW,
            RequestRoute.WEALTH_PURCHASE,
            RequestRoute.WEALTH_REDEEM,
            RequestRoute.AA_COLLECTION,
            RequestRoute.SUBSCRIPTION_CANCEL,
            RequestRoute.SUBSCRIPTION_RESUME,
        }:
            if self.requested_output is not RequestedOutput.WORKFLOW:
                raise ValueError("Workflow routes must request workflow output")
            return self
        if (
            self.route not in {RequestRoute.FINANCIAL_ANALYSIS, RequestRoute.PERSONAL_BANKING}
            and self.requested_output is not RequestedOutput.ANSWER
        ):
            raise ValueError("Only financial analysis can request a monthly report")
        if self.requested_output is RequestedOutput.WORKFLOW:
            raise ValueError("Only workflow routes can request workflow output")
        return self
