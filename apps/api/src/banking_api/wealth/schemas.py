from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from banking_api.domain.wealth import ProductRiskGrade
from banking_api.wealth.calculation import quantity
from banking_api.wealth.requirements import RecommendationConstraints


class WealthInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CompareInput(WealthInput):
    product_ids: list[str] = Field(min_length=1, max_length=4)


class RecommendationInput(WealthInput):
    needs: str = Field(default="", max_length=500)
    amount: str | None = None
    account_id: str | None = Field(default=None, max_length=100)

    @field_validator("amount")
    @classmethod
    def valid_amount(cls, value):
        if value is not None:
            quantity(value)
        return value


class AssessmentInput(WealthInput):
    questionnaire_version: Literal["mock-v1"]
    answers: list[Annotated[int, Field(strict=True, ge=0, le=4)]] = Field(
        min_length=8, max_length=8
    )


class WealthDraftInput(WealthInput):
    conversation_id: UUID | None = None
    creation_key: UUID | None = None
    redeem_all: bool = False
    direction: Literal["PURCHASE", "REDEEM"]
    product_id: str | None = Field(default=None, max_length=40)
    account_id: str | None = Field(default=None, max_length=100)
    quantity: str | None = None

    @field_validator("quantity")
    @classmethod
    def valid_quantity(cls, value, info):
        if value is not None:
            quantity(value, 2 if info.data.get("direction") == "PURCHASE" else 6)
        return value


class WealthEditInput(WealthInput):
    expected_version: int = Field(ge=1)
    redeem_all: bool = False
    product_id: str | None = Field(default=None, max_length=40)
    account_id: str | None = Field(default=None, max_length=100)
    quantity: str | None = None

    @field_validator("quantity")
    @classmethod
    def valid_quantity(cls, value):
        if value is not None:
            quantity(value, 6)
        return value


class WealthRiskDecision(BaseModel):
    requires_confirmation: bool = True
    requires_reauthentication: bool = True
    assessment_id: UUID | None = None
    customer_grade: str | None = None
    product_risk: ProductRiskGrade | None = None
    reasons: list[str] = []


class WealthProductResult(BaseModel):
    product_id: str
    version_id: str
    name: str
    risk: ProductRiskGrade
    minimum_display: str
    open_display: str
    fees_display: str
    nav_display: str | None
    nav_date: str | None
    change_display: str | None
    drawdown_display: str | None
    missing_reason: str | None
    sources: list[str]
    purchase_allowed: bool = False
    purchase_block_reason: str | None = None
    tradable: bool
    terms: dict


class WealthAssessmentResult(BaseModel):
    assessment_id: UUID
    grade_display: str
    score: int
    reasons: list[str]
    suitable: bool
    expires_at: datetime
    expired: bool
    questionnaire_version: str
    rules_version: str


class WealthKnowledgeResult(BaseModel):
    document_id: str
    version: str
    section: str
    source: str
    content: str


class WealthPositionResult(BaseModel):
    position_id: UUID
    product_id: str
    name: str
    account_id: str
    shares_display: str
    frozen_display: str
    available_display: str
    available_quantity: str = "0.000000"
    value_display: str | None
    valued_at: str | None
    pending_display: str


class WealthOrderResult(BaseModel):
    source_task_id: UUID | None = None
    conversation_id: UUID | None = None
    order_id: UUID
    workflow_id: UUID
    operation_id: UUID
    direction_display: str
    status_display: str
    name: str
    quantity_display: str
    trade_date: str
    confirm_at: datetime
    settle_at: datetime
    actual: dict[str, str] | None
    cash_result_label: str | None = None
    sources: list[str]
    unknown: bool
    error_code: str | None = None
    user_reason: str | None = None
    next_step: str | None = None
    last_known_stage: str | None = None
    next_processing_at: datetime | None = None
    hold_retained: bool = False


class WealthRecommendationResult(BaseModel):
    constraints: RecommendationConstraints | None = None
    selected_reasons: dict[str, list[str]] = {}
    products: list[WealthProductResult]
    reasons: list[str]
    excluded: dict[str, list[str]]


class WealthReadResult(BaseModel):
    constraints: RecommendationConstraints | None = None
    selected_reasons: dict[str, list[str]] = {}
    products: list[WealthProductResult] = []
    positions: list[WealthPositionResult] = []
    orders: list[WealthOrderResult] = []
    evidence: list[WealthKnowledgeResult] = []
    reasons: list[str] = []
    excluded: dict[str, list[str]] = {}


class WealthDraftResult(BaseModel):
    direction: Literal["PURCHASE", "REDEEM"]
    product_id: str | None = None
    account_id: str | None = None
    quantity: str | None = None
    quantity_unit: str | None = None
    redeem_all: bool = False


class WealthReviewResult(WealthDraftResult):
    account_display: str
    account_masked: str
    name: str
    version_id: str
    trade_date: str
    confirm_at: str
    settle_at: str
    quantity_display: str
    fee_display: str
    net_display: str
    shares_display: str
    notice: str
    sources: list[str]


class WealthWorkflowState(BaseModel):
    validation_message: str | None = None
    draft: WealthDraftResult
    review: WealthReviewResult | None = None


class WealthFeatureStatus(BaseModel):
    catalog_version: str | None = None
    pricing_version: str | None = None
    questionnaire_version: str = "mock-v1"
    new_business_allowed: bool
    reason: str
