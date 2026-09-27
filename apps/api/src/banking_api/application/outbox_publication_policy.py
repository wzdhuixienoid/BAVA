from dataclasses import dataclass
from datetime import timedelta

from banking_api.config.settings import Settings, get_settings


@dataclass(frozen=True)
class OutboxPublicationPolicy:
    lease_duration: timedelta
    initial_retry_delay: timedelta
    maximum_retry_delay: timedelta
    backoff_multiplier: int

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "OutboxPublicationPolicy":
        configured = settings or get_settings()
        return cls(
            lease_duration=timedelta(seconds=configured.outbox_publisher_lease_seconds),
            initial_retry_delay=timedelta(
                seconds=configured.outbox_publisher_initial_retry_seconds
            ),
            maximum_retry_delay=timedelta(
                seconds=configured.outbox_publisher_max_retry_seconds
            ),
            backoff_multiplier=configured.outbox_publisher_backoff_multiplier,
        )

    def retry_delay(self, attempt: int) -> timedelta:
        if attempt < 1:
            raise ValueError("attempt must be at least one")
        delay_seconds = self.initial_retry_delay.total_seconds()
        maximum_seconds = self.maximum_retry_delay.total_seconds()
        remaining_steps = attempt - 1
        while remaining_steps > 0 and delay_seconds < maximum_seconds:
            delay_seconds = min(
                delay_seconds * self.backoff_multiplier, maximum_seconds
            )
            remaining_steps -= 1
        return timedelta(seconds=min(delay_seconds, maximum_seconds))
