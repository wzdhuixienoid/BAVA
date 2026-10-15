import inspect
from typing import Any

from pydantic import BaseModel

from banking_api.domain.enums import PolicyDecision
from banking_api.domain.principal import ExecutionPrincipal, Principal
from banking_api.financial.errors import FinancialDomainError, FinancialErrorCode
from banking_api.policy.service import PolicyService
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.tools.models import (
    ToolError,
    ToolErrorCode,
    ToolExecutionContext,
    ToolExecutionResult,
)
from banking_api.wealth.calculation import WealthError


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, policy: PolicyService) -> None:
        self.registry = registry
        self.policy = policy

    async def execute(
        self,
        *,
        tool_name: str,
        arguments: Any,
        caller: str,
        principal: Principal | ExecutionPrincipal | None,
        agent_allowlist: frozenset[str],
    ) -> ToolExecutionResult:
        spec = self.registry.get_by_name(tool_name)
        if spec is None:
            return self._error(ToolErrorCode.TOOL_NOT_FOUND, "Tool is not registered")

        decision = self.policy.evaluate(
            spec=spec,
            caller=caller,
            authenticated=isinstance(principal, (Principal, ExecutionPrincipal))
            and bool(principal.user_id.strip()),
            agent_allowlist=agent_allowlist,
        )
        if decision.decision is not PolicyDecision.ALLOW:
            return self._error(ToolErrorCode.TOOL_NOT_ALLOWED, decision.reason)

        try:
            if isinstance(arguments, BaseModel):
                arguments = arguments.model_dump(round_trip=True, warnings="error")
            validated_input = spec.input_model.model_validate(arguments)
        except (ValueError, WealthError, TypeError):
            return self._error(
                ToolErrorCode.TOOL_ARGUMENT_VALIDATION_FAILED,
                "Tool arguments do not match the input schema",
                retryable=True,
                capability_id=spec.capability_id,
            )

        try:
            if principal is None:
                return self._error(
                    ToolErrorCode.TOOL_NOT_ALLOWED,
                    "Authenticated principal is required",
                    capability_id=spec.capability_id,
                )
            raw_output = spec.handler(ToolExecutionContext(principal), validated_input)
            if inspect.isawaitable(raw_output):
                raw_output = await raw_output
        except FinancialDomainError as exc:
            return self._error(
                exc.code,
                exc.message,
                capability_id=spec.capability_id,
            )
        except Exception:
            return self._error(
                ToolErrorCode.TOOL_EXECUTION_FAILED,
                "Tool execution failed",
                capability_id=spec.capability_id,
            )

        try:
            if isinstance(raw_output, BaseModel):
                raw_output = raw_output.model_dump(round_trip=True, warnings="error")
            output = spec.output_model.model_validate(raw_output)
            serialized = output.model_dump(mode="json", warnings="error")
        except (ValueError, TypeError):
            return self._error(
                ToolErrorCode.TOOL_OUTPUT_VALIDATION_FAILED,
                "Tool output does not match the output schema",
                capability_id=spec.capability_id,
            )
        return ToolExecutionResult(
            ok=True,
            capability_id=spec.capability_id,
            output=serialized,
        )

    @staticmethod
    def _error(
        code: ToolErrorCode | FinancialErrorCode,
        message: str,
        *,
        retryable: bool = False,
        capability_id: str | None = None,
    ) -> ToolExecutionResult:
        return ToolExecutionResult(
            ok=False,
            capability_id=capability_id,
            error=ToolError(code=code, message=message, retryable=retryable),
        )
