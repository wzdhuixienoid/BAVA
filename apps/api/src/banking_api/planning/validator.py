from pydantic import ValidationError

from banking_api.planning.constraints import has_conditional_control
from banking_api.planning.models import (
    PREDICATE_SOURCES,
    CapabilityStepProposal,
    ConditionStepProposal,
    PlanProposal,
    ValidatedPlan,
)
from banking_api.planning.registry import PlanCapabilityRegistry
from banking_api.planning.threshold_grounding import (
    ConditionThresholdGroundingValidator,
    ThresholdGroundingError,
)


class PlanValidationError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        self.message = (
            "请提供一个明确金额，例如：“如果余额不少于3000元，给张三转500元。”"
            if code
            in {"PLAN_CONDITION_THRESHOLD_REQUIRED", "PLAN_CONDITION_THRESHOLD_NOT_GROUNDED"}
            else "条件币种必须与原始请求一致；未说明币种时请勿指定币种"
            if code == "PLAN_CONDITION_CURRENCY_NOT_GROUNDED"
            else "当前计划无法安全执行，或包含不支持的能力"
        )
        super().__init__(code)


class PlanValidator:
    def __init__(self, registry: PlanCapabilityRegistry | None = None) -> None:
        self.registry = registry or PlanCapabilityRegistry()

    def parse(self, content: str, *, user_request: str | None = None) -> ValidatedPlan:
        try:
            proposal = PlanProposal.model_validate_json(content)
        except ValidationError as exc:
            code = "PLAN_SCHEMA_INVALID"
            for error in exc.errors():
                if error["type"] == "enum":
                    code = (
                        "PLAN_UNSUPPORTED_CONDITION"
                        if "predicate" in error["loc"]
                        else "PLAN_UNSUPPORTED_CAPABILITY"
                    )
            raise PlanValidationError(code) from exc
        validated = self.validate(proposal)
        return (
            self.validate_grounding(validated, user_request)
            if user_request is not None
            else validated
        )

    def validate(self, proposal: PlanProposal) -> ValidatedPlan:
        steps = {step.step_key: step for step in proposal.steps}
        if len(steps) != len(proposal.steps):
            raise PlanValidationError("PLAN_DUPLICATE_STEP_KEY")
        writes = 0
        conditions = [s for s in steps.values() if isinstance(s, ConditionStepProposal)]
        if len(conditions) > 2:
            raise PlanValidationError("PLAN_TOO_MANY_CONDITIONS")
        for step in steps.values():
            if len(set(step.depends_on)) != len(step.depends_on):
                raise PlanValidationError("PLAN_DUPLICATE_DEPENDENCY")
            if step.step_key in step.depends_on:
                raise PlanValidationError("PLAN_SELF_DEPENDENCY")
            if any(key not in steps for key in step.depends_on):
                raise PlanValidationError("PLAN_DEPENDENCY_MISSING")
            if isinstance(step, ConditionStepProposal):
                source = steps.get(step.condition.source_step_key)
                if source is None:
                    raise PlanValidationError("PLAN_CONDITION_SOURCE_MISSING")
                if isinstance(source, ConditionStepProposal):
                    raise PlanValidationError("PLAN_NESTED_CONDITION_UNSUPPORTED")
                if source.capability != PREDICATE_SOURCES[step.condition.predicate]:
                    raise PlanValidationError("PLAN_CONDITION_SOURCE_MISMATCH")
                if source.step_key not in step.depends_on:
                    raise PlanValidationError("PLAN_CONDITION_SOURCE_NOT_DEPENDENCY")
            else:
                if step.capability not in self.registry.definitions:
                    raise PlanValidationError("PLAN_UNSUPPORTED_CAPABILITY")
                if not self.registry.get(step.capability).read_only:
                    writes += 1
                    if step.subtask_query is not None:
                        raise PlanValidationError("PLAN_WRITE_QUERY_FORBIDDEN")
                guard = step.guard_condition_step_key
                if guard is not None:
                    if guard not in steps:
                        raise PlanValidationError("PLAN_GUARD_MISSING")
                    if not isinstance(steps[guard], ConditionStepProposal):
                        raise PlanValidationError("PLAN_GUARD_NOT_CONDITION")
                    if guard not in step.depends_on:
                        raise PlanValidationError("PLAN_GUARD_NOT_DEPENDENCY")
        if writes > 1:
            raise PlanValidationError("PLAN_MULTIPLE_WRITE_STEPS_UNSUPPORTED")
        if (
            not conditions
            and len({s.capability for s in steps.values() if isinstance(s, CapabilityStepProposal)})
            < 2
        ):
            raise PlanValidationError("PLAN_SINGLE_CAPABILITY_UNSUPPORTED")
        visited: set[str] = set()
        active: set[str] = set()

        def visit(key: str) -> None:
            if key in active:
                raise PlanValidationError("PLAN_CYCLE_DETECTED")
            if key in visited:
                return
            active.add(key)
            for dependency in steps[key].depends_on:
                visit(dependency)
            active.remove(key)
            visited.add(key)

        for key in steps:
            visit(key)
        for condition in conditions:
            pending = list(condition.depends_on)
            seen = set()
            while pending:
                ancestor = pending.pop()
                if ancestor in seen:
                    continue
                seen.add(ancestor)
                if isinstance(steps[ancestor], ConditionStepProposal):
                    raise PlanValidationError("PLAN_NESTED_CONDITION_UNSUPPORTED")
                pending.extend(steps[ancestor].depends_on)
        return ValidatedPlan(proposal=proposal)

    def validate_grounding(self, validated: ValidatedPlan, user_request: str) -> ValidatedPlan:
        grounding = ConditionThresholdGroundingValidator()
        try:
            steps = validated.proposal.steps
            conditions = [s for s in steps if isinstance(s, ConditionStepProposal)]
            if has_conditional_control(user_request):
                if not conditions:
                    grounding.require_explicit_thresholds(user_request)
                    raise PlanValidationError("PLAN_UNSUPPORTED_CONDITION")
                for step in steps:
                    if (
                        isinstance(step, CapabilityStepProposal)
                        and not self.registry.get(step.capability).read_only
                    ):
                        if step.guard_condition_step_key is None:
                            raise PlanValidationError("PLAN_GUARD_REQUIRED")
            normalized = []
            for step in steps:
                if isinstance(step, ConditionStepProposal):
                    source = grounding.validate(user_request, step.condition)
                    # Explicit user currency remains authoritative even if the proposal omits it.
                    step = step.model_copy(
                        update={
                            "condition": step.condition.model_copy(
                                update={"currency": source.currency}
                            )
                        }
                    )
                normalized.append(step)
            grounding.require_explicit_thresholds(user_request)
            return ValidatedPlan(
                proposal=validated.proposal.model_copy(update={"steps": normalized})
            )
        except ThresholdGroundingError as exc:
            raise PlanValidationError(exc.code) from exc
