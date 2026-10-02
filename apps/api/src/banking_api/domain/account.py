"""Critical account facts come from bank Tools; assistant prose is explanation only."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from banking_api.financial.report_formatter import ReportFormatter


class AccountSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str
    display_name: str
    account_type: str
    masked_number: str
    currency: str
    status: str


class AccountListResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["ACCOUNT_LIST"] = "ACCOUNT_LIST"
    accounts: list[AccountSummary] = Field(max_length=100)
    as_of: datetime


class AccountBalanceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["ACCOUNT_BALANCE"] = "ACCOUNT_BALANCE"
    account_id: str
    display_name: str
    masked_number: str
    account_type: str
    currency: str
    balance: Decimal = Field(allow_inf_nan=False)
    balance_display: str = ""
    as_of: datetime

    @field_validator("balance", mode="before")
    @classmethod
    def require_exact_balance(cls, value: object) -> object:
        if not isinstance(value, (str, Decimal)):
            raise ValueError("balance must be an exact decimal string")
        return value

    @field_serializer("balance")
    def serialize_balance(self, value: Decimal) -> str:
        return format(value, "f")

    @model_validator(mode="after")
    def format_balance(self) -> Self:
        self.balance_display = ReportFormatter().money(self.balance, self.currency)
        return self


AccountQueryResult = Annotated[
    AccountListResult | AccountBalanceResult, Field(discriminator="kind")
]
AccountQueryResults = Annotated[list[AccountQueryResult], Field(max_length=100)]
