from dataclasses import dataclass
from datetime import timedelta

from banking_api.config.settings import Settings, get_settings


@dataclass(frozen=True)
class TaskExecutionPolicy:
    """Deterministic lease and retry policy for durable Task execution."""

    lease_duration: timedelta
    heartbeat_interval: timedelta
    initial_retry_delay: timedelta
    maximum_retry_delay: timedelta
    backoff_multiplier: int

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "TaskExecutionPolicy":
        configured = settings or get_settings()
        return cls(
            lease_duration=timedelta(seconds=configured.task_worker_lease_seconds),
            heartbeat_interval=timedelta(
                seconds=configured.task_worker_heartbeat_seconds
            ),
            initial_retry_delay=timedelta(
                seconds=configured.task_worker_initial_retry_seconds
            ),
            maximum_retry_delay=timedelta(
                seconds=configured.task_worker_max_retry_seconds
            ),
            backoff_multiplier=configured.task_worker_backoff_multiplier,
        )

    def retry_delay(self, attempt: int) -> timedelta:
        if attempt < 1:
            raise ValueError("attempt must be at least one")
        delay = self.initial_retry_delay.total_seconds()
        maximum = self.maximum_retry_delay.total_seconds()
        for _ in range(attempt - 1):
            if delay >= maximum:
                break
            delay = min(delay * self.backoff_multiplier, maximum)
        return timedelta(seconds=min(delay, maximum))
