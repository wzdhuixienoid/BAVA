from calendar import monthrange
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import (
    MockSubscriptionCancellationModel,
    MockSubscriptionStateModel,
)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def next_billing(contract: dict, now: datetime) -> datetime:
    raw = contract.get("next_billing_at")
    anchor = utc(datetime.fromisoformat(str(raw).replace("Z", "+00:00"))) if raw else utc(now)
    months = 12 if contract["billing_interval"] == "ANNUAL" else 1
    candidate = anchor
    # Preserve the original calendar anchor (including month-end) across short months.
    step = 0 if raw else 1
    while candidate <= utc(now) or not raw and step == 1:
        index = anchor.year * 12 + anchor.month - 1 + months * step
        year, month = divmod(index, 12)
        month += 1
        day = min(anchor.day, monthrange(year, month)[1])
        candidate = anchor.replace(year=year, month=month, day=day)
        if candidate > utc(now):
            break
        step += 1
    return candidate


async def effective_contracts(
    bank: MockBankService, session: AsyncSession, user_id: str
) -> list[dict]:
    contracts = bank.list_subscriptions(user_id=user_id)
    states = {
        (row.subscription_id): row
        for row in (
            await session.execute(
                select(MockSubscriptionStateModel).where(
                    MockSubscriptionStateModel.user_id == user_id
                )
            )
        ).scalars()
    }
    legacy = set(
        (
            await session.execute(
                select(MockSubscriptionCancellationModel.subscription_id).where(
                    MockSubscriptionCancellationModel.user_id == user_id,
                    MockSubscriptionCancellationModel.status == "SUCCEEDED",
                )
            )
        ).scalars()
    )
    for item in contracts:
        state = states.get(item["subscription_id"])
        item["version"] = state.version if state else 0
        if state:
            item["status"] = state.status
            item["next_billing_at"] = (
                utc(state.next_billing_at).isoformat()
                if state.next_billing_at
                else item.get("next_billing_at")
            )
        elif item["subscription_id"] in legacy:
            item["status"] = "CANCELLED"
        item["cancellable"] = item["status"] == "ACTIVE" and bool(
            item.get("cancellation_supported", item["cancellable"])
        )
        item["resumable"] = item["status"] == "CANCELLED" and bool(
            item.get("resumption_supported", False)
        )
    return contracts
