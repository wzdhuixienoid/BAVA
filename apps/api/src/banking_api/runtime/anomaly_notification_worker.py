"""Detect posted consumption facts and persist one evidence-backed notice per transaction."""

import asyncio
import hashlib
import json
import logging

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from banking_api.application.account_statement_service import (
    AccountStatementService,
    PostedAnalysisBank,
)
from banking_api.config.demo_time import reference_now
from banking_api.financial.anomaly_detector import MAX_ANOMALIES, TransactionAnomalyDetector
from banking_api.financial.anomaly_models import TransactionAnomalyType
from banking_api.financial.presentation import transaction_time
from banking_api.persistence.models import NotificationModel

logger = logging.getLogger(__name__)
RULE_LABELS = {
    TransactionAnomalyType.AMOUNT_SPIKE: "金额明显高于历史",
    TransactionAnomalyType.RAPID_DUPLICATE: "同账户10分钟内同商户同金额重复扣款",
    TransactionAnomalyType.NEW_MERCHANT_HIGH_AMOUNT: "新商户高额消费",
    TransactionAnomalyType.SUBSCRIPTION_PRICE_SPIKE: "订阅价格明显上涨",
}


class AnomalyNotificationWorker:
    def __init__(self, factory, bank, *, clock=reference_now, poll_seconds=30):
        self.factory, self.bank, self.clock = factory, bank, clock
        self.poll_seconds = poll_seconds
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
                logger.exception("anomaly notification scan failed")
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                pass

    async def run_once(self):
        count = 0
        now = self.clock()
        for user_id in self.bank.list_user_ids():
            try:
                async with self.factory() as session, session.begin():
                    count += await self.scan_user(session, user_id, now)
            except Exception:
                # One user's unavailable facts must not prevent other users' scans.
                logger.exception("one account owner's anomaly scan failed")
        return count

    async def scan_user(self, session, user_id, now):
        rows = await AccountStatementService(self.bank, session).posted_transactions(
            user_id=user_id, as_of=now
        )
        accounts = {
            item["account_id"]: f"{item['display_name']} · {item['masked_number']}"
            for item in self.bank.list_accounts(user_id=user_id)
        }
        by_id = {row.transaction_id: row for row in rows}
        detector = TransactionAnomalyDetector(PostedAnalysisBank(self.bank, user_id, rows))
        count, offset = 0, 0
        while True:
            snapshot = detector.detect(user_id=user_id, generated_at=now, anomaly_offset=offset)
            for item in snapshot.anomalies:
                digest = hashlib.sha256(
                    json.dumps([user_id, item.transaction_id], ensure_ascii=False).encode()
                ).hexdigest()
                source = by_id[item.transaction_id]
                account = accounts[source.account_id]
                reasons = "、".join(RULE_LABELS[rule] for rule in item.anomaly_types)
                evidence = snapshot.model_copy(
                    update={
                        "anomalies": [item],
                        "total_anomaly_count": 1,
                        "truncated": False,
                    }
                )
                dialect = session.get_bind().dialect.name
                insert = pg_insert if dialect == "postgresql" else sqlite_insert
                statement = (
                    insert(NotificationModel)
                    .values(
                        user_id=user_id,
                        source_key=f"transaction-anomaly:{digest}",
                        kind="TRANSACTION_ANOMALY",
                        title="交易异常提示 · 请核对",
                        message=(
                            f"{transaction_time(item.occurred_at)}（北京时间），{account}在"
                            f"{item.merchant_display}支出{item.amount_display}：{reasons}。"
                            "这是规则提示，不代表已确认欺诈，不会自动冻结或扣款。"
                        ),
                        created_at=now,
                        anomaly_snapshot=evidence.model_dump(mode="json"),
                    )
                    .on_conflict_do_nothing(index_elements=["source_key"])
                    .returning(NotificationModel.notification_id)
                )
                count += (await session.scalar(statement)) is not None
            if not snapshot.truncated:
                return count
            offset += MAX_ANOMALIES
