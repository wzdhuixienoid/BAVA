"""Optional clock for synthetic read projections only. Security always uses real time."""

from datetime import UTC, datetime

from banking_api.config.settings import get_settings


def reference_now() -> datetime:
    settings = get_settings()
    return settings.demo_reference_time or datetime.now(UTC)
