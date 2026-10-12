from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from banking_api.domain.wealth import ProductRiskGrade
from banking_api.wealth.calculation import quantity
from banking_api.wealth.requirements import RecommendationConstraints
from banking_api.wealth.semantic import WealthIntentFrame


class WealthInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CompareInput(WealthInput):
    needs: str = Field(default="", max_length=500)
    amount: str | None = None
    account_id: str | None = Field(default=None, max_length=100)

    @field_validator("amount")
    @classmethod
    def valid_amount(cls, value):
        if value is not None:
            quantity(value)
        return value

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


class WealthDesignProfile(BaseModel):
    """Versioned fictional design, explicitly separate from trade terms and actual holdings."""

    version: str
    product_version_id: str
    published_at: str
    positioning: str
    strategy: str
    allocation: dict[str, int]
    return_sources: list[str]
    risk_drivers: list[str]
    scenarios: dict[str, str]
    suitable_for: str
    unsuitable_for: str
    observation_days: int
    observation_label: str
    growth_exposure: int
    concentration: int
    notice: str
    content_hash: str


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
    design_profile: WealthDesignProfile | None = None


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
    conversation_deleted: bool = False
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


class WealthNeeds(BaseModel):
    raw: str = ""
    amount: str | None = None
    account_id: str | None = None
    liquidity_raw: str | None = None
    return_goal: Literal["HIGHER_POTENTIAL", "GROWTH"] | None = None
    loss_tolerance_raw: str | None = None
    use_date_from: str | None = None
    use_date_to: str | None = None
    liquidity_basis: str | None = None
    priority: Literal["RISK", "LIQUIDITY", "FEES"] = "RISK"
    constraints: RecommendationConstraints = Field(default_factory=RecommendationConstraints)
    missing_fields: list[str] = []
    assumptions: list[str] = []
    clarification_questions: list[str] = []
    changed_fields: list[str] = []
    seek_alternatives: bool = False


class WealthEvidence(BaseModel):
    evidence_id: str
    title: str
    section: str
    scope: Literal["EDUCATION", "PRODUCT", "DESIGN"]
    source_type: str
    source_name: str
    url: str
    version: str
    verified_at: str | None = None
    published_at: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    content_hash: str
    content: str
    product_id: str | None = None
    version_id: str | None = None
    document_id: str | None = None


class WealthAnalysisBlock(BaseModel):
    block_id: str
    title: str
    text: str
    fact_ids: list[str] = []
    evidence_ids: list[str] = []


class WealthFeeScenario(BaseModel):
    amount: str
    budget_display: str
    nav: str
    nav_date: str
    purchase_rate: str
    redeem_rate: str
    purchase_fee_display: str
    redeem_fee_display: str
    total_fee_display: str
    estimated_cash_display: str
    shares: str
    assumption: str = (
        "假设申购和赎回净值均等于最新已发布净值；仅作费用情景，实际金额按未来净值成交。"
    )


class WealthTimingScenario(BaseModel):
    purchase: dict[str, str]
    redeem_existing: dict[str, str]
    earliest_redeem_new: dict[str, str]
    earliest_cash_at: str
    notice: str = (
        "Mock交易日仅周一至周五，不处理真实节假日。"
        "每日开放不等于实时到账；此为预估安排，并非已受理订单或到账保证。"
    )


class WealthHistoryWindow(BaseModel):
    start_date: str | None = None
    end_date: str | None = None
    data_as_of: str
    samples: int = 0
    change_display: str | None = None
    drawdown_display: str | None = None
    missing_reason: str | None = None
    notice: str = "统一近30日窗口，起点取不晚于目标日期的最近已发布净值；模拟历史不代表未来收益。"


class WealthCandidateAnalysis(BaseModel):
    purchase_entry_key: UUID | None = None
    product: WealthProductResult
    matched_conditions: list[str] = []
    advantages: list[str] = []
    limitations: list[str] = []
    unsuitable_when: list[str] = []
    unknowns: list[str] = []
    fact_id: str
    evidence_ids: list[str] = []
    fee_scenario: WealthFeeScenario | None = None
    timing: WealthTimingScenario
    history: WealthHistoryWindow


class WealthExcludedProduct(BaseModel):
    product_id: str
    version_id: str
    name: str
    reasons: list[str]


class WealthCustomerResponse(BaseModel):
    headline: str
    paragraphs: list[WealthAnalysisBlock] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    budget_display: str | None = None
    liquidity_display: str | None = None


class WealthAnswer(BaseModel):
    schema_version: Literal["wealth-answer-v1"] = "wealth-answer-v1"
    response_mode: str
    status: str
    headline: str
    paragraphs: list[WealthAnalysisBlock] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    fact_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    selected_product_id: str | None = None
    workflow_id: UUID | None = None
    generated_at: datetime
    source_task_id: UUID | None = None
    model: str | None = None
    skill_id: str
    skill_version: str
    generation_source: Literal["MODEL_GENERATED", "DETERMINISTIC_FALLBACK"]


class WealthPreviousProductContext(BaseModel):
    name: str
    positioning: str | None = None
    strategy: str | None = None
    return_sources: list[str] = Field(default_factory=list)
    risk_drivers: list[str] = Field(default_factory=list)


class WealthAnalysis(BaseModel):
    schema_version: Literal["wealth-analysis-v1", "wealth-analysis-v2"] = "wealth-analysis-v2"
    intent_frame: WealthIntentFrame | None = None
    answer: WealthAnswer | None = None
    snapshot_id: UUID
    source_task_id: UUID | None = None
    result_kind: Literal[
        "RECOMMENDATION",
        "COMPARISON",
        "EXPLANATION",
        "EDUCATION",
        "CATALOGUE",
        "PRODUCT_INTRO",
        "PREPARE_PURCHASE",
        "PREPARE_REDEEM",
        "PRODUCT_OVERVIEW",
    ]
    status: Literal[
        "NEEDS_ASSESSMENT", "NEEDS_CLARIFICATION", "CONDITIONAL", "MATCHED", "NO_MATCH", "EDUCATION"
    ]
    generated_at: datetime
    reference_time: datetime
    needs: WealthNeeds
    conclusion: str
    customer_response: WealthCustomerResponse | None = None
    assessment_id: UUID | None = None
    customer_grade: str | None = None
    assessment_expires_at: datetime | None = None
    assessment_rules_version: str | None = None
    excluded_products: list[WealthExcludedProduct] = []
    candidates: list[WealthCandidateAnalysis] = []
    blocks: list[WealthAnalysisBlock] = []
    evidence: list[WealthEvidence] = []
    excluded: dict[str, list[str]] = {}
    missing_data: list[str] = []
    ranking_basis: list[str] = []
    previous_snapshot_id: UUID | None = None
    historical_reference: str | None = None
    narrative_source: Literal[
        "DETERMINISTIC", "MODEL_ORGANIZED", "FALLBACK", "MODEL_GENERATED", "DETERMINISTIC_FALLBACK"
    ] = "DETERMINISTIC"
    degradation_reason: str | None = None
    validation_error: str | None = Field(default=None, exclude=True)
    new_business_allowed: bool = True
    considered_products: list[str] = Field(default_factory=list)
    recommendation_basis: list[str] = Field(default_factory=list)
    previous_product_names: list[str] = Field(default_factory=list)
    previous_product_context: list[WealthPreviousProductContext] = Field(default_factory=list)


class WealthAnalysisInput(RecommendationInput):
    intent_frame: WealthIntentFrame | None = None
    product_ids: list[str] = Field(default_factory=list, max_length=4)
    intent: Literal[
        "RECOMMENDATION",
        "COMPARISON",
        "EDUCATION",
        "EXPLANATION",
        "CATALOGUE",
        "PRODUCT_INTRO",
        "PREPARE_PURCHASE",
        "PREPARE_REDEEM",
        "PRODUCT_OVERVIEW",
    ] = "RECOMMENDATION"
    query: str = Field(default="", max_length=500)


class WealthRecommendationResult(BaseModel):
    analysis: WealthAnalysis | None = None
    constraints: RecommendationConstraints | None = None
    selected_reasons: dict[str, list[str]] = {}
    products: list[WealthProductResult]
    reasons: list[str]
    excluded: dict[str, list[str]]


class WealthReadResult(BaseModel):
    result_kind: (
        Literal[
            "CATALOGUE",
            "PRODUCT",
            "COMPARISON",
            "RECOMMENDATION",
            "KNOWLEDGE",
            "POSITIONS",
            "ORDERS",
        ]
        | None
    ) = None
    analysis: WealthAnalysis | None = None
    constraints: RecommendationConstraints | None = None
    selected_reasons: dict[str, list[str]] = {}
    products: list[WealthProductResult] = []
    positions: list[WealthPositionResult] = []
    orders: list[WealthOrderResult] = []
    evidence: list[WealthKnowledgeResult] = []
    evidence_sources: list[WealthEvidence] = []
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
    order_received: bool = False
    order_stage: str | None = None
    purchase_entry_allowed: bool = True
    purchase_entry_block_reason: str | None = None
    validation_message: str | None = None
    draft: WealthDraftResult
    review: WealthReviewResult | None = None


class WealthFeatureStatus(BaseModel):
    catalog_version: str | None = None
    pricing_version: str | None = None
    questionnaire_version: str = "mock-v1"
    new_business_allowed: bool
    reason: str
