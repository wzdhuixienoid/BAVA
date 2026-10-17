from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from test_transaction_anomalies import baseline, transaction

from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import (
    MockSubscriptionChargeModel,
    NotificationModel,
    OperationModel,
)
from banking_api.runtime.anomaly_notification_worker import AnomalyNotificationWorker
from banking_api.transfers.mock_provider import MockTransferProvider

USER = "dev-user-001"
NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)


def fact(row, user=USER, **updates):
    return {**row, "account_id": "acc_salary", "user_id": user, **updates}


def runtime(app, *, users=frozenset({USER})):
    bank = MockBankService(fixture_user_ids=users)
    bank._transactions = []
    clock = [NOW]
    worker = AnomalyNotificationWorker(app.state.test_session_factory, bank, clock=lambda: clock[0])
    return bank, clock, worker


def spike_rows(user=USER):
    return [fact(row, user) for row in baseline(NOW)] + [
        fact(transaction("spike", NOW - timedelta(days=1), "新商户", "900"), user)
    ]


async def test_backfill_new_posted_and_restart_read_delete_never_repeat(app, client):
    bank, clock, worker = runtime(app)
    bank._transactions = spike_rows()
    provider = MockTransferProvider(app.state.test_session_factory, bank)
    before = await provider.effective_balance(USER, "acc_salary")
    assert await worker.run_once() == 1
    inbox = (await client.get("/api/v1/notifications")).json()
    assert inbox["unread_count"] == 1
    notice = inbox["items"][0]
    assert notice["kind"] == "TRANSACTION_ANOMALY"
    assert "工资卡 · ****6688" in notice["message"] and "900.00" in notice["message"]
    assert "2026" in notice["message"] and "不代表已确认欺诈" in notice["message"]
    assert len(notice["anomaly_snapshot"]["anomalies"]) == 1
    identity = notice["notification_id"]
    snapshot = (await client.get(f"/api/v1/notifications/{identity}")).json()["anomaly_snapshot"]
    assert (await client.post(f"/api/v1/notifications/{identity}/read")).status_code == 200
    assert (await client.delete(f"/api/v1/notifications/{identity}")).status_code == 204
    assert await worker.run_once() == 0
    assert (await client.get(f"/api/v1/notifications/{identity}")).status_code == 404
    restarted = AnomalyNotificationWorker(
        app.state.test_session_factory, bank, clock=lambda: clock[0]
    )
    assert await restarted.run_once() == 0
    bank._transactions.append(
        fact(transaction("later", NOW - timedelta(seconds=1), "第二商户", "900"))
    )
    assert await restarted.run_once() == 1
    # Age out of the rolling scan: original evidence stays unchanged in durable storage.
    clock[0] += timedelta(days=40)
    assert await restarted.run_once() == 0
    async with app.state.test_session_factory() as session:
        original = await session.get(NotificationModel, UUID(identity))
        assert original.anomaly_snapshot == snapshot
        assert await session.scalar(select(func.count()).select_from(NotificationModel)) == 2
        assert await session.scalar(select(func.count()).select_from(OperationModel)) == 0
    assert await provider.effective_balance(USER, "acc_salary") == before


async def test_users_with_same_transaction_ids_get_separate_owned_evidence(app, client):
    bank, _, worker = runtime(app, users=frozenset({USER, "other-user"}))
    bank._transactions = spike_rows() + spike_rows("other-user")
    assert await worker.run_once() == 2
    async with app.state.test_session_factory() as session:
        rows = (await session.scalars(select(NotificationModel))).all()
        assert len({row.source_key for row in rows}) == 2
        foreign = next(row for row in rows if row.user_id == "other-user")
    assert (await client.get(f"/api/v1/notifications/{foreign.notification_id}")).status_code == 404
    inbox = (await client.get("/api/v1/notifications")).json()
    assert len(inbox["items"]) == 1


async def test_only_posted_debits_are_analyzed_and_accounts_are_separate(app):
    bank, _, worker = runtime(app)
    first = fact(transaction("one", NOW - timedelta(minutes=2), "商户", "100"))
    bank._transactions = [
        first,
        {**first, "transaction_id": "other-card", "account_id": "acc_savings"},
    ]
    for index, updates in enumerate(
        [
            {"status": "PENDING"},
            {"direction": "CREDIT"},
            {"category": "TRANSFER"},
            {"occurred_at": (NOW + timedelta(minutes=1)).isoformat()},
        ]
    ):
        bank._transactions.append({**first, "transaction_id": str(index), **updates})
    assert await worker.run_once() == 0
    bank._transactions.append(
        {
            **first,
            "transaction_id": "same-card",
            "occurred_at": (NOW - timedelta(minutes=1)).isoformat(),
        }
    )
    assert await worker.run_once() == 1
    async with app.state.test_session_factory() as session:
        row = await session.scalar(select(NotificationModel))
        item = row.anomaly_snapshot["anomalies"][0]
        assert item["transaction_id"] == "same-card"
        assert set(item["related_transaction_ids"]) == {"one", "same-card"}


async def test_succeeded_subscription_charge_uses_same_posted_ledger(app):
    bank, _, worker = runtime(app)
    bank._transactions = [
        fact(
            transaction("old", NOW - timedelta(days=32), "星幕视频", "30", category="SUBSCRIPTION")
        )
    ]
    async with app.state.test_session_factory() as session:
        for index, status in enumerate(["FAILED", "PENDING", "SUCCEEDED"]):
            session.add(
                MockSubscriptionChargeModel(
                    user_id=USER,
                    subscription_id=f"sub-{index}",
                    source_account_id="acc_salary",
                    merchant="星幕视频",
                    amount=Decimal("42"),
                    currency="CNY",
                    billing_at=NOW - timedelta(seconds=1),
                    created_at=NOW - timedelta(seconds=1),
                    status=status,
                )
            )
        await session.commit()
    assert await worker.run_once() == 1
    async with app.state.test_session_factory() as session:
        notice = await session.scalar(select(NotificationModel))
        item = notice.anomaly_snapshot["anomalies"][0]
        assert item["transaction_id"].startswith("subscription:")
        assert "SUBSCRIPTION_PRICE_SPIKE" in item["anomaly_types"]


async def test_scan_does_not_lose_anomalies_after_fifty_item_display_limit(app):
    bank, _, worker = runtime(app)
    for index in range(60):
        for day in [89, 60, 40]:
            bank._transactions.append(
                fact(
                    transaction(
                        f"base-{index}-{day}", NOW - timedelta(days=day), f"商户{index}", "100"
                    )
                )
            )
        bank._transactions.append(
            fact(transaction(f"spike-{index}", NOW - timedelta(hours=1), f"商户{index}", "900"))
        )
    assert await worker.run_once() == 60
    assert await worker.run_once() == 0
    async with app.state.test_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(NotificationModel)) == 60
