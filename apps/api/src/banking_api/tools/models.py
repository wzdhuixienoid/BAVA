from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from banking_api.domain.account import AccountListResult
from banking_api.domain.enums import RiskLevel
from banking_api.domain.principal import ExecutionPrincipal, Principal
from banking_api.financial.errors import FinancialErrorCode


class ListAccountsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


ListAccountsOutput = AccountListResult


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


class ListPayeesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offset: int = Field(default=0, ge=0)


class ListPayeesOutput(BaseModel):
    payees: list[PayeeSummary] = Field(max_length=100)


class TransferOperationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: UUID


class TransferCommitOutput(BaseModel):
    outcome: Literal["ACCEPTED", "FAILED", "UNKNOWN"]
    provider_reference: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class TransferStatusOutput(BaseModel):
    status: Literal["SUCCEEDED", "FAILED", "PENDING", "UNKNOWN"]
    provider_reference: str | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    principal: Principal | ExecutionPrincipal


ToolHandler = Callable[[ToolExecutionContext, BaseModel], BaseModel | Awaitable[BaseModel]]


class ToolSpec(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True, extra="forbid", frozen=True, revalidate_instances="always"
    )

    capability_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    description: str = Field(min_length=1)
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    risk_level: RiskLevel
    side_effect: bool
    allowed_callers: frozenset[str]
    handler: ToolHandler

    @model_validator(mode="after")
    def validate_contract(self):
        if not self.description.strip() or not self.allowed_callers:
            raise ValueError("Tools require a description and explicit callers")
        if self.input_model is BaseModel or self.output_model is BaseModel:
            raise ValueError("Tools require concrete argument and output model classes")
        schema = self.input_schema
        if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            raise ValueError("Tool arguments require an object schema rejecting unknown fields")
        if self.output_schema.get("type") != "object":
            raise ValueError("Tools require structured object output schemas")
        if self.risk_level is RiskLevel.R1_PRIVATE_READ:
            if self.side_effect:
                raise ValueError("Read tools cannot have side effects")
        elif self.risk_level in {RiskLevel.R3_FINANCIAL_RECONCILE, RiskLevel.R4_FINANCIAL_COMMIT}:
            if not self.side_effect or any(
                not c.startswith("workflow:") for c in self.allowed_callers
            ):
                raise ValueError(
                    "Financial mutations require workflow-only callers and side effects"
                )
        else:
            raise ValueError("Unsupported tool risk classification")
        return self

    @property
    def input_schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()

    @property
    def output_schema(self) -> dict[str, Any]:
        return self.output_model.model_json_schema(mode="serialization")


class ToolErrorCode(StrEnum):
    USER_CONFIRMATION_REQUIRED = "USER_CONFIRMATION_REQUIRED"
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
