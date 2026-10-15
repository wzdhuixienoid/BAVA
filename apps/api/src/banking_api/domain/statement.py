"""Bounded, owner-scoped queries over the posted cash ledger."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from banking_api.domain.dashboard import DashboardTransaction
from banking_api.financial.models import FinancialPeriodInput


class AccountStatementInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: str | None = Field(default=None, description="北京时间自然月 YYYY-MM 或自然年 YYYY。")
    recent_days: int | None = Field(
        default=None, ge=1, le=36600, description="最近N天，未指定期间默认30天。"
    )
    start_at: datetime | None = Field(default=None, description="带时区的起点，包含。")
    end_at: datetime | None = Field(default=None, description="带时区的终点，不包含。")
    account_ids: list[str] | None = Field(default=None, min_length=1, max_length=10)
    category: str | None = Field(
        default=None,
        min_length=1,
        max_length=40,
        description="分类代码，如 TRANSFER、SHOPPING、SUBSCRIPTION、WEALTH、SALARY。",
    )
    direction: Literal["DEBIT", "CREDIT"] | None = Field(
        default=None,
        description="DEBIT支出/转给别人，CREDIT收入/收到转账；不填表示两者。姓名query不隐含方向。",
    )
    source: Literal["BANK", "TRANSFER", "SUBSCRIPTION", "WEALTH"] | None = None
    query: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="对手方/商户名称或备注包含的文字，不是收款人ID。",
    )
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=50)
    as_of: datetime | None = Field(
        default=None, description="继续翻页时复用上一页as_of，首查留空。"
    )

    @model_validator(mode="after")
    def validate_query(self):
        self.period_input()  # Reuse period exclusivity and timezone validation.
        if self.as_of is not None and self.as_of.tzinfo is None:
            raise ValueError("as_of必须包含时区")
        if self.category is not None:
            from banking_api.financial.presentation import CATEGORY_LABELS

            if self.category not in CATEGORY_LABELS:
                raise ValueError("请使用有效的分类代码")
        return self

    def period_input(self) -> FinancialPeriodInput:
        period = {k: getattr(self, k) for k in ("month", "recent_days", "start_at", "end_at")}
        if all(v is None for v in period.values()):
            period["recent_days"] = 30
        return FinancialPeriodInput(**period)


class StatementTransaction(DashboardTransaction):
    account_display: str
    category_display: str
    occurred_at_display: str
    status: Literal["POSTED"] = "POSTED"


class StatementCurrencyTotal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    currency: str
    debit_count: int
    credit_count: int
    total_debit: Decimal
    total_credit: Decimal
    debit_display: str
    credit_display: str


class StatementCounterpartyTotal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    counterparty_key: str
    display_name: str
    identity_known: bool
    direction: Literal["DEBIT", "CREDIT"]
    currency: str
    transaction_count: int
    amount: Decimal
    amount_display: str
    share_display: str


class StatementSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_transfer: bool
    scope_display: str
    totals: list[StatementCurrencyTotal]
    counterparties: list[StatementCounterpartyTotal] = Field(max_length=20)
    counterparty_group_count: int
    latest_transaction: StatementTransaction | None
    insights: list[str]
    grouping_note: str | None = None


class AccountStatementResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: datetime
    start_at: datetime
    end_at: datetime
    transactions: list[StatementTransaction] = Field(max_length=50)
    total_count: int = Field(ge=0)
    offset: int = Field(ge=0)
    next_offset: int | None
    summary: StatementSummary | None = None
    answer: str | None = None
    posting_scope: str = "仅包含已实际入账流水；待处理、失败、预约和冻结资金不等于已入账。"
