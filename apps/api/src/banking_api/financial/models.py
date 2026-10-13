from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from banking_api.financial.errors import FinancialDomainError, FinancialErrorCode
from banking_api.financial.presentation import category_label, transaction_time
from banking_api.financial.review_models import SpendingReview


class FinancialPeriodInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    include_review: bool | None = Field(
        default=None, description="默认附简短交易核对提示；用户明确拒绝异常检查时关闭。"
    )

    month: str | None = Field(
        default=None, description="自然月 YYYY-MM 或自然年 YYYY；与时间区间、recent_days 互斥。"
    )
    start_at: datetime | None = Field(default=None, description="区间起点，带时区，包含该时刻。")
    end_at: datetime | None = Field(default=None, description="区间终点，带时区，不包含该时刻。")
    recent_days: int | None = Field(default=None, ge=1, description="从当前业务时间向前的天数。")
    account_ids: list[str] | None = None

    @model_validator(mode="after")
    def validate_period(self):
        has_range = self.start_at is not None or self.end_at is not None
        if sum([self.month is not None, self.recent_days is not None, has_range]) != 1:
            raise ValueError("请提供且仅提供月份、最近天数或起止时间中的一种")
        if has_range:
            if self.start_at is None or self.end_at is None:
                raise ValueError("请同时提供起止时间")
            if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
                raise ValueError("起止时间必须包含时区")
            if self.start_at >= self.end_at:
                raise ValueError("起点必须早于终点")
        return self

    def resolve_period(self, now: datetime) -> str:
        if self.month is not None:
            return self.month
        if self.recent_days is not None:
            try:
                return f"{(now - timedelta(days=self.recent_days)).isoformat()}/{now.isoformat()}"
            except (OverflowError, ValueError) as exc:
                raise FinancialDomainError(
                    FinancialErrorCode.INVALID_PERIOD,
                    "天数超出可处理的日期范围，请提供有效起止日期",
                ) from exc
        return f"{self.start_at.isoformat()}/{self.end_at.isoformat()}"


class TopTransactionsInput(FinancialPeriodInput):
    limit: int = Field(default=5, ge=1, le=20)


class SpendingSummary(BaseModel):
    spending_review: SpendingReview | None = None
    period: str
    total_income: Decimal
    total_spending: Decimal
    income_transaction_count: int
    spending_transaction_count: int
    currency: str


class CategorySpending(BaseModel):
    category: str
    amount: Decimal
    transaction_count: int
    share: Decimal

    @computed_field
    @property
    def category_display(self) -> str:
        return category_label(self.category)

    @computed_field
    @property
    def share_display(self) -> str:
        percent = (self.share * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"{percent:.2f}%"


class CategoryBreakdown(BaseModel):
    period: str
    total_spending: Decimal
    currency: str
    categories: list[CategorySpending]


class CategoryChange(BaseModel):
    category: str
    current_amount: Decimal
    previous_amount: Decimal
    absolute_change: Decimal
    percentage_change: Decimal | None

    @computed_field
    @property
    def category_display(self) -> str:
        return category_label(self.category)


class SpendingPeriodComparison(BaseModel):
    current_period: str
    previous_period: str
    current_spending: Decimal
    previous_spending: Decimal
    absolute_change: Decimal
    percentage_change: Decimal | None
    currency: str
    category_changes: list[CategoryChange]


class TopTransaction(BaseModel):
    transaction_id: str
    occurred_at: datetime
    merchant: str
    description: str
    category: str
    amount: Decimal
    currency: str
    account_id: str
    account_display: str = "账户"

    @computed_field
    @property
    def category_display(self) -> str:
        return category_label(self.category)

    @computed_field
    @property
    def occurred_at_display(self) -> str:
        return transaction_time(self.occurred_at)


class TopTransactions(BaseModel):
    period: str
    currency: str
    transactions: list[TopTransaction]


class SpendingTransactions(BaseModel):
    transactions: list[TopTransaction]
    total_count: int
    offset: int
    available_months: list[str]
    available_categories: list[str]
