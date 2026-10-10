from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from zoneinfo import ZoneInfo

CN = ZoneInfo("Asia/Shanghai")
CENT = Decimal("0.01")
UNIT = Decimal("0.000001")
MAX = Decimal("999999999999.99")


class WealthError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def quantity(value, places=2):
    if isinstance(value, (float, bool)):
        raise WealthError("INVALID_QUANTITY", "金额或份额请使用十进制字符串")
    try:
        number = Decimal(value)
        if not number.is_finite() or number <= 0 or number > MAX:
            raise InvalidOperation
        if number.as_tuple().exponent < -places:
            raise InvalidOperation
    except (InvalidOperation, TypeError, ValueError):
        raise WealthError("INVALID_QUANTITY", "金额或份额必须为正数且不能超出精度或上限") from None
    return number


def purchase(amount, nav, rate):
    fee = (amount * rate).quantize(CENT, ROUND_HALF_UP)
    shares = ((amount - fee) / nav).quantize(UNIT, ROUND_DOWN)
    cost = (shares * nav).quantize(CENT, ROUND_HALF_UP)
    refund = amount - fee - cost
    if shares <= 0 or refund < 0:
        raise WealthError("PRICING_BOUNDARY", "计价边界无法满足正份额与非负余款，请调整金额")
    return {"fee": fee, "shares": shares, "cost": cost, "refund": refund, "net": cost}


def redeem(shares, nav, rate):
    cost = (shares * nav).quantize(CENT, ROUND_HALF_UP)
    fee = (cost * rate).quantize(CENT, ROUND_HALF_UP)
    return {"fee": fee, "shares": shares, "cost": cost, "refund": Decimal(0), "net": cost - fee}


def next_day(day: date) -> date:
    day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def schedule(now: datetime, weekdays: list[int], direction: str) -> dict:
    local = now.astimezone(CN)
    day = local.date()
    if local.time() >= time(15):
        day += timedelta(days=1)
    while day.weekday() not in weekdays:
        day += timedelta(days=1)
    confirm_day = next_day(day)
    confirm = datetime.combine(confirm_day, time(10), CN)
    settle = (
        confirm
        if direction == "PURCHASE"
        else datetime.combine(next_day(confirm_day), time(10), CN)
    )
    return {
        "trade_date": day.isoformat(),
        "confirm_at": confirm.isoformat(),
        "settle_at": settle.isoformat(),
    }
