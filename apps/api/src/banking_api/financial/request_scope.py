"""Ground rolling windows and anomaly access in the current user request."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from banking_api.agents.models import AgentDefinition

_RECENT_DAYS = re.compile(
    r"(?:最近|近|过去|前)?\s*([0-9０-９]+|[零〇一二两三四五六七八九十百千万]+)\s*天"
)


def _days(value: str) -> int:
    if value.isdecimal():
        return int(value)
    digits = dict(
        zip("零〇一二两三四五六七八九", [0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9], strict=True)
    )
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    total = section = number = 0
    for char in value:
        if char in digits:
            number = digits[char]
        elif char == "万":
            total += (section + number) * 10000
            section = number = 0
        else:
            section += (number or 1) * units[char]
            number = 0
    return total + section + number


def anomaly_requested(text: str) -> bool:
    text = re.sub(
        r"(?:不要|不用|无需|不需要|别)[^，。；\n]*?(?:异常|奇怪扣款|可疑|盗刷)[^，。；\n]*",
        "",
        text,
    )
    return bool(
        re.search(r"异常|奇怪扣款|可疑|盗刷|不明扣款|重复扣(?:款|费)|不认识的(?:交易|扣款)", text)
    )


def declines_anomaly_review(text: str) -> bool:
    return bool(
        re.search(r"(?:不要|不用|无需|不需要|别)[^，。；\n]*?(?:异常|可疑|核对|风险检查)", text)
    )


@dataclass(frozen=True)
class FinancialRequestScope:
    window: dict[str, str] | None = None
    clarification: str | None = None


def request_scope(
    text: str, now: datetime, *, include_calendar: bool = False
) -> FinancialRequestScope:
    # A date-only endpoint includes that day's transactions in Beijing time.
    patterns = [
        r"(?P<year>\d{4})[-/](?P<month>\d{1,2})[-/](?P<day>\d{1,2})",
        r"(?:(?P<year>\d{4})年)?(?P<month>\d{1,2})月(?P<day>\d{1,2})[日号]?",
    ]
    date_matches = []
    for pattern in patterns:
        date_matches.extend(re.finditer(pattern, text))
    date_matches.sort(key=lambda match: match.start())
    if date_matches:
        if len(date_matches) > 2:
            return FinancialRequestScope(clarification="请提供一个明确的起止日期区间。")
        try:
            dates = []
            timed = []
            current_year = now.astimezone(timezone(timedelta(hours=8))).year
            for match in date_matches:
                year = int(match.group("year")) if match.group("year") else current_year
                dates.append(
                    datetime(
                        year,
                        int(match.group("month")),
                        int(match.group("day")),
                        tzinfo=timezone(timedelta(hours=8)),
                    )
                )
                clock = re.match(r"[ T]*(\d{1,2})[:：](\d{2})(?::(\d{2}))?", text[match.end() :])
                timed.append(clock is not None)
                if clock:
                    dates[-1] = dates[-1].replace(
                        hour=int(clock.group(1)),
                        minute=int(clock.group(2)),
                        second=int(clock.group(3) or 0),
                    )
                current_year = year
            if len(dates) == 2:
                start, end = dates[0], dates[1] if timed[1] else dates[1] + timedelta(days=1)
                if start >= end:
                    raise ValueError("起止日期顺序错误")
            elif re.search(r"至今|到现在|至现在|到今天|至今天", text):
                start, end = dates[0], now
            elif timed[0] or re.search(r"从|起|开始|至|到", text):
                return FinancialRequestScope(clarification="请补充要分析的结束日期。")
            else:
                start, end = dates[0], dates[0] + timedelta(days=1)
            return FinancialRequestScope(
                window={"start_at": start.isoformat(), "end_at": end.isoformat()}
            )
        except (ValueError, OverflowError):
            return FinancialRequestScope(
                clarification="起止日期无效，请提供有效且起点不晚于终点的日期。"
            )
    if include_calendar:
        calendar = re.search(r"(?P<year>\d{4})年(?:(?P<month>\d{1,2})月)?", text)
        if calendar or re.search(r"去年|今年|本月|上月", text):
            local = now.astimezone(timezone(timedelta(hours=8)))
            year = int(calendar.group("year")) if calendar else local.year - ("去年" in text)
            month = int(calendar.group("month")) if calendar and calendar.group("month") else None
            if not calendar and re.search(r"本月|上月", text):
                month = local.month
                if "上月" in text:
                    month -= 1
                    if month == 0:
                        month, year = 12, year - 1
            try:
                start = datetime(year, month or 1, 1, tzinfo=local.tzinfo)
                end = (
                    datetime(year + 1, 1, 1, tzinfo=local.tzinfo)
                    if month is None
                    else (
                        datetime(year + 1, 1, 1, tzinfo=local.tzinfo)
                        if month == 12
                        else datetime(year, month + 1, 1, tzinfo=local.tzinfo)
                    )
                )
                return FinancialRequestScope(
                    window={"start_at": start.isoformat(), "end_at": end.isoformat()}
                )
            except ValueError:
                return FinancialRequestScope(clarification="请提供有效的年份或月份。")
    year_match = re.search(
        r"(?:近|最近|过去)\s*([0-9０-９]+|[零〇一二两三四五六七八九十百千万]+)年", text
    )
    if year_match:
        years = _days(year_match.group(1))
        if years < 1 or years >= now.year:
            return FinancialRequestScope(clarification="请提供有效的年份范围。")
        try:
            start = now.replace(year=now.year - years)
        except ValueError:
            start = now.replace(year=now.year - years, day=28)
        return FinancialRequestScope(
            window={"start_at": start.isoformat(), "end_at": now.isoformat()}
        )
    matches = _RECENT_DAYS.findall(text)
    if matches:
        values = {_days(value) for value in matches}
        if len(values) != 1 or next(iter(values)) < 1:
            return FinancialRequestScope(
                clarification="请明确一个正整数天数，或提供要分析的起止日期。"
            )
        try:
            start = now - timedelta(days=next(iter(values)))
        except (OverflowError, ValueError):
            return FinancialRequestScope(
                clarification="该天数超出可处理的日期范围，请提供有效的起止日期。"
            )
        return FinancialRequestScope(
            window={"start_at": start.isoformat(), "end_at": now.isoformat()}
        )
    if (
        re.search(r"最近|近期|近来|这段时间|前些天", text)
        and re.search(r"消费|支出|花销|花费|开销|账单", text)
        and not re.search(
            r"(?:[0-9０-９零〇一二两三四五六七八九十百千万]+|本|上|这|去|今)\s*(?:个)?(?:年|月|周|季度)"
            r"|(?:几|多少|若干)\s*天",
            text,
        )
    ):
        return FinancialRequestScope(
            window={"start_at": (now - timedelta(days=30)).isoformat(), "end_at": now.isoformat()}
        )
    if re.search(r"(?:最近|过去|前)\s*(?:几|多少|若干)\s*天|这段时间|一段时间|前些天", text):
        return FinancialRequestScope(
            clarification="请告诉我要分析最近多少天，或提供明确的起止日期。"
        )
    return FinancialRequestScope()


def restrict_financial_agent(agent: AgentDefinition, text: str) -> AgentDefinition:
    if agent.agent_id != "agent:financial-analysis" or anomaly_requested(text):
        return agent
    return AgentDefinition(
        agent_id=agent.agent_id,
        instructions=agent.instructions
        + "\n本次用户没有要求异常交易分析，不得调用异常识别工具或改做异常分析。",
        allowed_capabilities=agent.allowed_capabilities - {"transaction.detect_anomalies"},
    )
