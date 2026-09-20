import inspect
from typing import Any

from pydantic import ValidationError

from banking_api.domain.enums import PolicyDecision
from banking_api.policy.service import PolicyService
from banking_api.registries.tool_registry import ToolRegistry
from banking_api.tools.models import ToolError, ToolErrorCode, ToolExecutionResult


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
        authenticated: bool,
        agent_allowlist: frozenset[str],
    ) -> ToolExecutionResult:
        spec = self.registry.get_by_name(tool_name)
        if spec is None:
            return self._error(ToolErrorCode.TOOL_NOT_FOUND, "Tool is not registered")

        decision = self.policy.evaluate(
            spec=spec,
            caller=caller,
            authenticated=authenticated,
            agent_allowlist=agent_allowlist,
        )
        if decision.decision is not PolicyDecision.ALLOW:
            return self._error(ToolErrorCode.TOOL_NOT_ALLOWED, decision.reason)

        try:
            validated_input = spec.input_model.model_validate(arguments)
        except ValidationError:
            return self._error(
                ToolErrorCode.TOOL_ARGUMENT_VALIDATION_FAILED,
                "Tool arguments do not match the input schema",
                retryable=True,
                capability_id=spec.capability_id,
            )

        try:
            raw_output = spec.handler(validated_input)
            if inspect.isawaitable(raw_output):
                raw_output = await raw_output
        except Exception:
            return self._error(
                ToolErrorCode.TOOL_EXECUTION_FAILED,
                "Tool execution failed",
                capability_id=spec.capability_id,
            )

        try:
            output = spec.output_model.model_validate(raw_output)
        except ValidationError:
            return self._error(
                ToolErrorCode.TOOL_OUTPUT_VALIDATION_FAILED,
                "Tool output does not match the output schema",
                capability_id=spec.capability_id,
            )
        return ToolExecutionResult(
            ok=True,
            capability_id=spec.capability_id,
            output=output.model_dump(mode="json"),
        )

    @staticmethod
    def _error(
        code: ToolErrorCode,
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
