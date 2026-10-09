from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.config.demo_time import reference_now
from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import MockSubscriptionChargeModel
from banking_api.subscriptions.contracts import effective_contracts
from banking_api.subscriptions.contracts import next_billing as future_billing
from banking_api.subscriptions.detector import (
    MAX_EVIDENCE_IDS,
    SubscriptionDetector,
    normalize_merchant,
)
from banking_api.subscriptions.models import (
    BillingInterval,
    CurrencyCost,
    DuplicateCandidate,
    SubscriptionAnalysisSnapshot,
    SubscriptionItem,
    SubscriptionManagementType,
    SubscriptionStatus,
)


class SubscriptionNotFoundError(Exception):
    pass


class SubscriptionAnalysisService:
    def __init__(self, bank: MockBankService, session: AsyncSession) -> None:
        self.bank = bank
        self.session = session
        self.detector = SubscriptionDetector()

    async def analyze(
        self,
        *,
        user_id: str,
        generated_at: datetime | None = None,
        upcoming_days: int = 7,
    ) -> SubscriptionAnalysisSnapshot:
        now = generated_at or reference_now()
        transactions = self.bank.list_transactions(user_id=user_id)
        charges = (
            await self.session.scalars(
                select(MockSubscriptionChargeModel).where(
                    MockSubscriptionChargeModel.user_id == user_id,
                    MockSubscriptionChargeModel.status == "SUCCEEDED",
                )
            )
        ).all()
        transactions.extend(
            {
                "transaction_id": str(row.charge_id),
                "merchant": row.merchant,
                "amount": str(row.amount),
                "currency": row.currency,
                "occurred_at": row.created_at.isoformat(),
                "status": "POSTED",
                "direction": "DEBIT",
                "category": "SUBSCRIPTION",
            }
            for row in charges
        )
        detected = self.detector.detect(transactions)
        contracts = await effective_contracts(self.bank, self.session, user_id)
        cancellations = {
            str(item["subscription_id"]) for item in contracts if item["status"] == "CANCELLED"
        }
        contracts_by_key: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
        for contract in contracts:
            contracts_by_key[
                (normalize_merchant(str(contract["merchant"])), str(contract["currency"]).upper())
            ].append(contract)

        items: list[SubscriptionItem] = []
        for candidate in detected:
            matching = contracts_by_key.get((candidate.merchant_key, candidate.currency), [])
            contract = matching[0] if len(matching) == 1 else None
            price_amount, price_percent = self.detector.price_change(candidate)
            last_date = self.detector._occurred_at(candidate.last).date()
            evidence_ids = [str(row["transaction_id"]) for row in candidate.charges]
            if contract is None:
                item = SubscriptionItem(
                    merchant=candidate.merchant,
                    management_type=SubscriptionManagementType.DETECTED_ONLY,
                    status=SubscriptionStatus.ACTIVE,
                    billing_interval=candidate.billing_interval,
                    last_charge_amount=self.detector.amount(candidate.last),
                    currency=candidate.currency,
                    last_charge_date=last_date,
                    next_billing_at=self.detector.estimated_next_billing(candidate),
                    next_billing_is_estimated=True,
                    evidence_count=len(candidate.charges),
                    evidence_transaction_ids=evidence_ids[-MAX_EVIDENCE_IDS:],
                    price_change_amount=price_amount,
                    price_change_percent=price_percent,
                    cancellable=False,
                )
            else:
                subscription_id = str(contract["subscription_id"])
                status = (
                    SubscriptionStatus.CANCELLED
                    if subscription_id in cancellations or contract["status"] == "CANCELLED"
                    else SubscriptionStatus.ACTIVE
                )
                next_billing = (
                    datetime.fromisoformat(str(contract["next_billing_at"]).replace("Z", "+00:00"))
                    if contract.get("next_billing_at") and status is SubscriptionStatus.ACTIVE
                    else None
                )
                if next_billing and next_billing <= now:
                    next_billing = future_billing(contract, now)
                item = SubscriptionItem(
                    subscription_id=subscription_id,
                    contract_version=int(contract["version"]),
                    contract_amount=Decimal(str(contract["amount"])),
                    billing_anchor_at=datetime.fromisoformat(
                        str(contract["next_billing_at"]).replace("Z", "+00:00")
                    )
                    if contract.get("next_billing_at")
                    else None,
                    resumable=bool(contract["resumable"]),
                    merchant=str(contract["merchant"]),
                    plan_name=str(contract["plan_name"]),
                    management_type=SubscriptionManagementType.MANAGED,
                    status=status,
                    billing_interval=BillingInterval(str(contract["billing_interval"])),
                    last_charge_amount=self.detector.amount(candidate.last),
                    currency=candidate.currency,
                    last_charge_date=last_date,
                    next_billing_at=next_billing,
                    next_billing_is_estimated=False,
                    evidence_count=len(candidate.charges),
                    evidence_transaction_ids=evidence_ids[-MAX_EVIDENCE_IDS:],
                    price_change_amount=price_amount,
                    price_change_percent=price_percent,
                    cancellable=(
                        status is SubscriptionStatus.ACTIVE and bool(contract["cancellable"])
                    ),
                )
            items.append(item)

        present = {item.subscription_id for item in items}
        for contract in contracts:
            if contract["subscription_id"] in present:
                continue
            items.append(
                SubscriptionItem(
                    subscription_id=contract["subscription_id"],
                    merchant=contract["merchant"],
                    plan_name=contract["plan_name"],
                    management_type=SubscriptionManagementType.MANAGED,
                    status=SubscriptionStatus(contract["status"]),
                    billing_interval=BillingInterval(contract["billing_interval"]),
                    last_charge_amount=Decimal("0"),
                    currency=contract["currency"],
                    last_charge_date=None,
                    next_billing_at=(
                        future_billing(contract, now)
                        if contract.get("next_billing_at") and contract["status"] == "ACTIVE"
                        else None
                    ),
                    next_billing_is_estimated=False,
                    evidence_count=0,
                    evidence_transaction_ids=[],
                    cancellable=contract["cancellable"],
                    resumable=contract["resumable"],
                    contract_version=contract["version"],
                    contract_amount=Decimal(str(contract["amount"])),
                    billing_anchor_at=datetime.fromisoformat(
                        str(contract["next_billing_at"]).replace("Z", "+00:00")
                    )
                    if contract.get("next_billing_at")
                    else None,
                )
            )

        monthly: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        annual: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for item in items:
            if item.status is not SubscriptionStatus.ACTIVE:
                continue
            if item.billing_interval is BillingInterval.MONTHLY:
                item.monthly_cost = (
                    item.contract_amount
                    if item.contract_amount is not None
                    else item.last_charge_amount
                )
                item.annual_projected_cost = item.monthly_cost * Decimal("12")
            else:
                item.annual_projected_cost = (
                    item.contract_amount
                    if item.contract_amount is not None
                    else item.last_charge_amount
                )
                item.monthly_cost = (
                    item.contract_amount
                    if item.contract_amount is not None
                    else item.last_charge_amount / Decimal("12")
                )
            item.format_display()
            monthly[item.currency] += item.monthly_cost
            annual[item.currency] += item.annual_projected_cost

        cutoff = now + timedelta(days=upcoming_days)
        upcoming = [
            item
            for item in items
            if item.status is SubscriptionStatus.ACTIVE
            and item.next_billing_at is not None
            and now <= item.next_billing_at <= cutoff
        ]
        counts = Counter(
            normalize_merchant(str(contract["merchant"]))
            for contract in contracts
            if str(contract["status"]) == "ACTIVE"
            and str(contract["subscription_id"]) not in cancellations
        )
        duplicates = [
            DuplicateCandidate(
                merchant=key,
                subscription_ids=sorted(
                    str(contract["subscription_id"])
                    for contract in contracts
                    if normalize_merchant(str(contract["merchant"])) == key
                    and str(contract["status"]) == "ACTIVE"
                    and str(contract["subscription_id"]) not in cancellations
                ),
            )
            for key, count in sorted(counts.items())
            if count > 1
        ]
        ordered = sorted(items, key=lambda item: (item.status.value, item.merchant, item.currency))
        return SubscriptionAnalysisSnapshot(
            subscriptions=ordered[:50],
            monthly_cost_by_currency=[
                CurrencyCost(currency=currency, amount=amount)
                for currency, amount in sorted(monthly.items())
            ],
            annual_projected_cost_by_currency=[
                CurrencyCost(currency=currency, amount=amount)
                for currency, amount in sorted(annual.items())
            ],
            upcoming_renewals=sorted(upcoming, key=lambda item: item.next_billing_at or now)[:20],
            price_changes=[item for item in ordered if item.price_change_amount is not None][:20],
            duplicate_candidates=duplicates,
            generated_at=now,
        )

    async def get(self, subscription_id: str, *, user_id: str) -> SubscriptionItem:
        snapshot = await self.analyze(user_id=user_id, upcoming_days=90)
        item = next(
            (item for item in snapshot.subscriptions if item.subscription_id == subscription_id),
            None,
        )
        if item is None:
            raise SubscriptionNotFoundError
        return item
