from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class FinancialPeriodInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: str = Field(
        description="分析期间：自然月 YYYY-MM，或自然年 YYYY；年份根据业务参考日期确定。"
    )
    account_ids: list[str] | None = None


class TopTransactionsInput(FinancialPeriodInput):
    limit: int = Field(default=5, ge=1, le=20)


class SpendingSummary(BaseModel):
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


class TopTransactions(BaseModel):
    period: str
    currency: str
    transactions: list[TopTransaction]
