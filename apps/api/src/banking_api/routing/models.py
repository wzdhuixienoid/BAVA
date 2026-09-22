from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RequestRoute(StrEnum):
    MINIMAL_BANKING = "MINIMAL_BANKING"
    FINANCIAL_ANALYSIS = "FINANCIAL_ANALYSIS"
    UNSUPPORTED = "UNSUPPORTED"


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: RequestRoute
    confidence: float = Field(ge=0, le=1)
