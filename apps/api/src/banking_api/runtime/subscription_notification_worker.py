"""Read-only polling of renewal dates and newly observed POSTED subscription debits."""

import asyncio
import hashlib
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from banking_api.persistence.models import NotificationModel, SubscriptionNotificationCursorModel
from banking_api.security.guard import acquire_security_user_lock
from banking_api.subscriptions.billing import bill_subscription
from banking_api.subscriptions.contracts import effective_contracts, next_billing, utc
from banking_api.subscriptions.detector import SubscriptionDetector, normalize_merchant

logger = logging.getLogger(__name__)


class SubscriptionNotificationWorker:
    def __init__(
        self,
        factory,
        bank,
        *,
        transfer_provider=None,
        billing_enabled=False,
        clock=lambda: datetime.now(UTC),
        poll_seconds=30,
    ):
        self.factory, self.bank, self.clock = factory, bank, clock
        self.poll_seconds = poll_seconds
        self.transfer_provider, self.billing_enabled = transfer_provider, billing_enabled
        self.stop_event = asyncio.Event()
        self.task = None

    def start(self):
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        self.stop_event.set()
        if self.task:
            await self.task

    async def run(self):
        while not self.stop_event.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("subscription notification scan failed")
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                pass

    async def run_once(self):
        now = utc(self.clock())
        count = 0
        for user_id in self.bank.list_user_ids():
            async with self.factory() as session:
                async with session.begin():
                    await acquire_security_user_lock(session, user_id)
                    # Serialize cursor + notification writes across API processes.
                    if session.get_bind().dialect.name == "postgresql":
                        digest = hashlib.sha256(f"subscription-notices:{user_id}".encode()).digest()
                        await session.execute(
                            text("SELECT pg_advisory_xact_lock(:key)"),
                            {"key": int.from_bytes(digest[:8], "big", signed=True)},
                        )
                    count += await self.scan_user(session, user_id, now)
        return count

    async def scan_user(self, session, user_id, now):
        cursor = await session.get(SubscriptionNotificationCursorModel, user_id)
        first_scan = cursor is None
        if first_scan:
            cursor = SubscriptionNotificationCursorModel(
                user_id=user_id, seen_transaction_ids=[], last_billing_scan_at=now
            )
            session.add(cursor)
        contracts = await effective_contracts(self.bank, session, user_id)
        billed_count = 0
        if self.billing_enabled and not first_scan:
            for contract in contracts:
                if contract["status"] != "ACTIVE" or not contract.get("next_billing_at"):
                    continue
                due = next_billing(contract, utc(cursor.last_billing_scan_at))
                while due <= now:
                    charge = await bill_subscription(
                        session, self.bank, self.transfer_provider, contract, due, now
                    )
                    if charge is None:
                        break
                    success = charge.status == "SUCCEEDED"
                    reason = {
                        "INSUFFICIENT_FUNDS": "余额不足",
                        "SECURITY_WRITE_LOCKED": "账户暂时限制支出",
                        "SUBSCRIPTION_ACCOUNT_MISSING": "未绑定扣费账户",
                        "SUBSCRIPTION_ACCOUNT_INVALID": "扣费账户不可用或币种不匹配",
                    }.get(charge.error_code, "扣费失败，请检查订阅")
                    billed_count += await self.notify(
                        session,
                        user_id,
                        f"subscription:{user_id}:billing:{contract['subscription_id']}:{due.isoformat()}",
                        "SUBSCRIPTION_CHARGE",
                        "订阅模拟扣费成功" if success else "订阅模拟扣费失败",
                        f"{charge.merchant} 本期模拟扣费 ¥{charge.amount:.2f}，"
                        + ("已从签约账户扣除。" if success else f"未扣款，原因：{reason}。"),
                        now,
                    )
                    contract = next(
                        c
                        for c in await effective_contracts(self.bank, session, user_id)
                        if c["subscription_id"] == contract["subscription_id"]
                    )
                    due = next_billing(contract, due)
            contracts = await effective_contracts(self.bank, session, user_id)
        cursor.last_billing_scan_at = max(utc(cursor.last_billing_scan_at), now)
        transactions = [
            row
            for row in self.bank.list_transactions(user_id=user_id)
            if SubscriptionDetector._occurred_at(row) <= now
        ]
        candidates = SubscriptionDetector().detect(transactions)
        known_keys = {(normalize_merchant(c["merchant"]), c["currency"]) for c in contracts}
        detected_keys = {(c.merchant_key, c.currency) for c in candidates}
        count = billed_count
        for contract in contracts:
            if contract["status"] != "ACTIVE" or not contract.get("next_billing_at"):
                continue
            due = next_billing(contract, now - timedelta(microseconds=1))
            count += await self.remind(
                session,
                user_id,
                contract["subscription_id"],
                contract["merchant"],
                contract["amount"],
                contract["currency"],
                due,
                now,
            )
        for candidate in candidates:
            if (candidate.merchant_key, candidate.currency) in known_keys:
                continue
            anchor = SubscriptionDetector.estimated_next_billing(candidate)
            due = next_billing(
                {
                    "next_billing_at": anchor.isoformat(),
                    "billing_interval": candidate.billing_interval.value,
                },
                now - timedelta(microseconds=1),
            )
            count += await self.remind(
                session,
                user_id,
                f"detected:{candidate.merchant_key}:{candidate.currency}",
                candidate.merchant,
                str(SubscriptionDetector.amount(candidate.last)),
                candidate.currency,
                due,
                now,
                estimated=True,
            )
        charges = [
            row
            for row in transactions
            if row.get("status") == "POSTED"
            and row.get("direction") == "DEBIT"
            and (
                row.get("category") == "SUBSCRIPTION"
                or (normalize_merchant(row["merchant"]), row["currency"])
                in known_keys | detected_keys
            )
        ]
        # Baseline pre-existing history on first startup; it is not a new debit event.
        seen = set(cursor.seen_transaction_ids)
        for row in charges:
            tx_id = str(row["transaction_id"])
            if tx_id not in seen and not first_scan:
                when = SubscriptionDetector._occurred_at(row).astimezone(ZoneInfo("Asia/Shanghai"))
                count += await self.notify(
                    session,
                    user_id,
                    f"subscription:{user_id}:charge:{tx_id}",
                    "SUBSCRIPTION_CHARGE",
                    "订阅扣费已入账",
                    f"{row['merchant']} 已扣费 "
                    f"¥{Decimal(str(row['amount'])):.2f}，"
                    f"扣费时间 {when:%Y-%m-%d %H:%M}（北京时间）。",
                    now,
                )
            seen.add(tx_id)
        cursor.seen_transaction_ids = sorted(seen)
        return count

    async def remind(
        self, session, user_id, identity, merchant, amount, currency, due, now, *, estimated=False
    ):
        if not due - timedelta(days=7) <= now < due:
            return 0
        due_local = due.astimezone(ZoneInfo("Asia/Shanghai"))
        hint = (
            "预计扣费日期，实际以商户扣费为准。"
            if estimated
            else "如需取消订阅，请在扣费前前往订阅管理办理取消。"
        )
        return await self.notify(
            session,
            user_id,
            f"subscription:{user_id}:renewal:{identity}:{due.isoformat()}",
            "SUBSCRIPTION_RENEWAL",
            "订阅续费提醒",
            f"{merchant} 将于 {due_local:%Y-%m-%d %H:%M}（北京时间）"
            f"{'预计' if estimated else ''}续费 ¥{Decimal(str(amount)):.2f}。{hint}",
            now,
        )

    @staticmethod
    async def notify(session, user_id, key, kind, title, message, now):
        if await session.scalar(
            select(NotificationModel).where(NotificationModel.source_key == key)
        ):
            return 0
        session.add(
            NotificationModel(
                user_id=user_id,
                source_key=key,
                kind=kind,
                title=title,
                message=message,
                created_at=now,
            )
        )
        await session.flush()
        return 1
