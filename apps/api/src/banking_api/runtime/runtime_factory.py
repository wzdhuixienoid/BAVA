from banking_api.domain.enums import RuntimeBackend
from banking_api.runtime.base import AgentRuntime


class AgentRuntimeFactory:
    def __init__(self) -> None:
        self._runtimes: dict[RuntimeBackend, AgentRuntime] = {}

    def register(self, backend: RuntimeBackend, runtime: AgentRuntime) -> None:
        self._runtimes[backend] = runtime

    def get(self, backend: RuntimeBackend) -> AgentRuntime:
        try:
            return self._runtimes[backend]
        except KeyError as exc:
            raise ValueError(f"Runtime backend is not configured: {backend.value}") from exc
