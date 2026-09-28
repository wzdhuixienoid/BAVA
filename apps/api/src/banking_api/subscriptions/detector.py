import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from typing import Any

from banking_api.subscriptions.models import BillingInterval

MONTHLY_MIN_DAYS = 25
MONTHLY_MAX_DAYS = 35
ANNUAL_MIN_DAYS = 350
ANNUAL_MAX_DAYS = 380
MIN_EVIDENCE_COUNT = 2
MAX_EVIDENCE_IDS = 6


MERCHANT_ALIASES = {
    "星幕视频": "星幕视频",
    "星幕视频会员": "星幕视频",
    "STARSCREENVIDEO": "星幕视频",
    "海浪音乐": "海浪音乐",
    "海浪音乐会员": "海浪音乐",
    "云笺存储": "云笺存储",
    "像素设计": "像素设计",
    "活力健身": "活力健身",
    "晨光健身": "晨光健身",
    "晨光健身月卡": "晨光健身",
}


def _alias_key(value: str) -> str:
    return re.sub(r"[^0-9A-Z\u4e00-\u9fff]+", "", value.upper())


def normalize_merchant(value: str) -> str:
    """Normalize only explicit fixture aliases; unknown merchants remain distinct."""

    key = _alias_key(value)
    return MERCHANT_ALIASES.get(key, key)


class DetectedSubscription:
    def __init__(
        self,
        *,
        merchant_key: str,
        merchant: str,
        currency: str,
        billing_interval: BillingInterval,
        charges: list[dict[str, Any]],
    ) -> None:
        self.merchant_key = merchant_key
        self.merchant = merchant
        self.currency = currency
        self.billing_interval = billing_interval
        self.charges = charges

    @property
    def last(self) -> dict[str, Any]:
        return self.charges[-1]

    @property
    def previous(self) -> dict[str, Any]:
        return self.charges[-2]


class SubscriptionDetector:
    """Deterministic cadence detection over authoritative application transactions."""

    def detect(self, transactions: list[dict[str, Any]]) -> list[DetectedSubscription]:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for item in transactions:
            if (
                item.get("status") != "POSTED"
                or item.get("direction") != "DEBIT"
                or item.get("category") == "TRANSFER"
            ):
                continue
            merchant_key = normalize_merchant(str(item["merchant"]))
            # The synthetic dataset has an explicit subscription category plus a
            # small reviewed alias fixture for periodic charges categorized elsewhere.
            # This keeps rent and utilities from becoming accidental "subscriptions".
            if item.get("category") != "SUBSCRIPTION" and merchant_key not in set(
                MERCHANT_ALIASES.values()
            ):
                continue
            grouped[(merchant_key, str(item["currency"]).upper())].append(item)

        detected: list[DetectedSubscription] = []
        for (merchant_key, currency), items in sorted(grouped.items()):
            ordered = sorted(items, key=self._occurred_at)
            if len(ordered) < MIN_EVIDENCE_COUNT:
                continue
            intervals = [
                (self._occurred_at(current) - self._occurred_at(previous)).days
                for previous, current in zip(ordered, ordered[1:], strict=False)
            ]
            cadence = self._cadence(intervals)
            if cadence is None:
                continue
            detected.append(
                DetectedSubscription(
                    merchant_key=merchant_key,
                    merchant=str(ordered[-1]["merchant"]),
                    currency=currency,
                    billing_interval=cadence,
                    charges=ordered,
                )
            )
        return detected

    @staticmethod
    def _cadence(intervals: list[int]) -> BillingInterval | None:
        if intervals and all(MONTHLY_MIN_DAYS <= days <= MONTHLY_MAX_DAYS for days in intervals):
            return BillingInterval.MONTHLY
        if intervals and all(ANNUAL_MIN_DAYS <= days <= ANNUAL_MAX_DAYS for days in intervals):
            return BillingInterval.ANNUAL
        return None

    @staticmethod
    def _occurred_at(item: dict[str, Any]) -> datetime:
        parsed = datetime.fromisoformat(str(item["occurred_at"]).replace("Z", "+00:00"))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone(UTC)

    @staticmethod
    def amount(item: dict[str, Any]) -> Decimal:
        return Decimal(str(item["amount"]))

    @classmethod
    def price_change(cls, item: DetectedSubscription) -> tuple[Decimal | None, Decimal | None]:
        current = cls.amount(item.last)
        previous = cls.amount(item.previous)
        if current == previous:
            return None, None
        change = current - previous
        if previous == Decimal("0"):
            return change, None
        with localcontext() as context:
            context.prec = 28
            return change, change / previous * Decimal("100")

    @classmethod
    def estimated_next_billing(cls, item: DetectedSubscription) -> datetime:
        days = 30 if item.billing_interval is BillingInterval.MONTHLY else 365
        return cls._occurred_at(item.last) + timedelta(days=days)
