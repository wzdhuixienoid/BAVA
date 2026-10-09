import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from banking_api.config.settings import get_settings


def parse_execution_time(expression: str, received_at: datetime) -> tuple[datetime, datetime]:
    settings = get_settings()
    local = received_at.astimezone(ZoneInfo(settings.banking_business_timezone))
    expression = expression.strip()
    match = re.fullmatch(
        r"(今天|明天|后天)(上午|早上|早晨|下午|晚上)?\s*(\d{1,2})\s*(?:点|:)(?:(\d{1,2})(?:分)?)?",
        expression,
    )
    if match:
        day, period, hour, minute = match.groups()
        if period in {"早上", "早晨"}:
            period = "上午"
        hour, minute = int(hour), int(minute or 0)
        if period in {"上午", "晚上"} and hour == 12:
            raise ValueError("SCHEDULE_TIME_AMBIGUOUS")
        if period and not 1 <= hour <= 12:
            raise ValueError("SCHEDULE_TIME_AMBIGUOUS")
        if period in {"下午", "晚上"}:
            hour = hour % 12 + 12
        if period == "上午":
            hour %= 12
        when = (local + timedelta(days={"今天": 0, "明天": 1, "后天": 2}[day])).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
    else:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?", expression):
            raise ValueError("SCHEDULE_TIME_AMBIGUOUS")
        when = datetime.fromisoformat(expression.replace("T", " ")).replace(tzinfo=local.tzinfo)
    when = when.astimezone(UTC)
    advance = (when - received_at.astimezone(UTC)).total_seconds()
    if advance < settings.scheduled_transfer_min_advance_seconds:
        raise ValueError("SCHEDULE_TIME_TOO_SOON")
    if advance > settings.scheduled_transfer_max_days * 86400:
        raise ValueError("SCHEDULE_TIME_TOO_FAR")
    return when, when + timedelta(seconds=settings.scheduled_transfer_late_window_seconds)


def is_monthly_expression(expression: str) -> bool:
    return bool(re.match(r"\s*每(?:个)?月", expression))


def parse_monthly_recurrence(expression: str, received_at: datetime):
    """Finite monthly scope; omit nonexistent dates rather than silently change the day."""
    import calendar

    from banking_api.workflows.transfer.models import MonthlyRecurrence

    settings = get_settings()
    local = received_at.astimezone(ZoneInfo(settings.banking_business_timezone))
    match = re.fullmatch(
        r"每(?:个)?月(\d{1,2})(?:号|日)(上午|早上|早晨|下午|晚上)?"
        r"(\d{1,2})(?:点|:)(?:(\d{1,2})(?:分)?)?[，,、]?共(\d{1,2})次",
        "".join(expression.split()),
    )
    if not match:
        raise ValueError("RECURRENCE_DETAILS_REQUIRED")
    day, period, hour, minute, count = match.groups()
    day, hour, minute, count = int(day), int(hour), int(minute or 0), int(count)
    if (
        not 1 <= day <= 31
        or not 0 <= minute <= 59
        or not 2 <= count <= settings.recurring_transfer_max_occurrences
    ):
        raise ValueError("RECURRENCE_INVALID")
    if period:
        if not 1 <= hour <= 12 or (period in {"上午", "早上", "早晨", "晚上"} and hour == 12):
            raise ValueError("SCHEDULE_TIME_AMBIGUOUS")
        hour = hour % 12 + (12 if period in {"下午", "晚上"} else 0)
    if not 0 <= hour <= 23:
        raise ValueError("SCHEDULE_TIME_AMBIGUOUS")
    dates = []
    month_index = local.year * 12 + local.month - 1
    for offset in range(36):
        year, month = divmod(month_index + offset, 12)
        month += 1
        if day > calendar.monthrange(year, month)[1]:
            continue
        when = datetime(year, month, day, hour, minute, tzinfo=local.tzinfo).astimezone(UTC)
        if (
            when - received_at.astimezone(UTC)
        ).total_seconds() < settings.scheduled_transfer_min_advance_seconds:
            continue
        if (
            when - received_at.astimezone(UTC)
        ).total_seconds() > settings.recurring_transfer_max_days * 86400:
            raise ValueError("RECURRENCE_TOO_FAR")
        dates.append(when)
        if len(dates) == count:
            return MonthlyRecurrence(
                day=day, hour=hour, minute=minute, count=count, occurrences=dates
            )
    raise ValueError("RECURRENCE_TOO_FAR")
