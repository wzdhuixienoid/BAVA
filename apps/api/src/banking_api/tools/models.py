from collections.abc import Awaitable, Callable
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from banking_api.domain.enums import RiskLevel
from banking_api.financial.errors import FinancialErrorCode


class ListAccountsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccountSummary(BaseModel):
    account_id: str
    display_name: str
    account_type: str
    masked_number: str
    currency: str
    status: str


class ListAccountsOutput(BaseModel):
    accounts: list[AccountSummary]


class GetBalanceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str = Field(min_length=1)


class BalanceResult(BaseModel):
    account_id: str
    display_name: str
    masked_number: str
    currency: str
    balance: Decimal


class SearchPayeesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=100)


class PayeeSummary(BaseModel):
    payee_id: str
    display_name: str
    bank_name: str
    masked_account: str
    phone_alias: str


class SearchPayeesOutput(BaseModel):
    payees: list[PayeeSummary] = Field(max_length=10)


ToolHandler = Callable[[BaseModel], BaseModel | Awaitable[BaseModel]]


class ToolSpec(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    capability_id: str
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    risk_level: RiskLevel
    side_effect: bool
    allowed_callers: frozenset[str]
    handler: ToolHandler

    @property
    def input_schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()

    @property
    def output_schema(self) -> dict[str, Any]:
        return self.output_model.model_json_schema()


class ToolErrorCode(StrEnum):
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED"
    TOOL_ARGUMENT_VALIDATION_FAILED = "TOOL_ARGUMENT_VALIDATION_FAILED"
    TOOL_OUTPUT_VALIDATION_FAILED = "TOOL_OUTPUT_VALIDATION_FAILED"
    TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"


class ToolErrorDisposition(StrEnum):
    RECOVERABLE = "RECOVERABLE"
    FATAL = "FATAL"


class ToolError(BaseModel):
    code: ToolErrorCode | FinancialErrorCode
    message: str
    retryable: bool = False

    @property
    def disposition(self) -> ToolErrorDisposition:
        if self.code is ToolErrorCode.TOOL_ARGUMENT_VALIDATION_FAILED or isinstance(
            self.code, FinancialErrorCode
        ):
            return ToolErrorDisposition.RECOVERABLE
        return ToolErrorDisposition.FATAL


class ToolExecutionResult(BaseModel):
    ok: bool
    capability_id: str | None = None
    output: dict[str, Any] | None = None
    error: ToolError | None = None
