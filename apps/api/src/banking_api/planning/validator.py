from pydantic import ValidationError

from banking_api.planning.models import PlanProposal, ValidatedPlan
from banking_api.planning.registry import PlanCapabilityRegistry


class PlanValidationError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class PlanValidator:
    def __init__(self, registry: PlanCapabilityRegistry | None = None) -> None:
        self.registry = registry or PlanCapabilityRegistry()

    def parse(self, content: str) -> ValidatedPlan:
        try:
            proposal = PlanProposal.model_validate_json(content)
        except ValidationError as exc:
            code = "PLAN_SCHEMA_INVALID"
            if any(error["type"] == "enum" for error in exc.errors()):
                code = "PLAN_UNSUPPORTED_CAPABILITY"
            raise PlanValidationError(code) from exc
        return self.validate(proposal)

    def validate(self, proposal: PlanProposal) -> ValidatedPlan:
        steps = {step.step_key: step for step in proposal.steps}
        if len(steps) != len(proposal.steps):
            raise PlanValidationError("PLAN_DUPLICATE_STEP_KEY")
        writes = 0
        for step in steps.values():
            if step.capability not in self.registry.definitions:
                raise PlanValidationError("PLAN_UNSUPPORTED_CAPABILITY")
            if not self.registry.get(step.capability).read_only:
                writes += 1
                if step.subtask_query is not None:
                    raise PlanValidationError("PLAN_WRITE_QUERY_FORBIDDEN")
            if len(set(step.depends_on)) != len(step.depends_on):
                raise PlanValidationError("PLAN_DUPLICATE_DEPENDENCY")
            if step.step_key in step.depends_on:
                raise PlanValidationError("PLAN_SELF_DEPENDENCY")
            if any(key not in steps for key in step.depends_on):
                raise PlanValidationError("PLAN_DEPENDENCY_MISSING")
        if writes > 1:
            raise PlanValidationError("PLAN_MULTIPLE_WRITE_STEPS_UNSUPPORTED")
        if len({step.capability for step in steps.values()}) < 2:
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
        return ValidatedPlan(proposal=proposal)
