from typing import Any


class WorkflowRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Any] = {}

    def register(self, workflow_type: str, workflow: Any) -> None:
        if workflow_type in self._items:
            raise ValueError(f"Workflow already registered: {workflow_type}")
        self._items[workflow_type] = workflow

    def get(self, workflow_type: str) -> Any | None:
        return self._items.get(workflow_type)

