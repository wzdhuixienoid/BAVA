"""Generate the committed deterministic synthetic banking fixtures."""

import json
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from random import Random

SEED = 20260920
DATA_DIR = Path(__file__).parents[1] / "apps/api/src/banking_api/mock_bank/data"


def write(name: str, rows: list[dict[str, object]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / name).write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def transaction(
    sequence: int,
    *,
    account_id: str,
    day: date,
    merchant: str,
    description: str,
    amount: str,
    direction: str,
    category: str,
) -> dict[str, object]:
    occurred = datetime(day.year, day.month, day.day, 12, sequence % 60, tzinfo=UTC)
    return {
        "transaction_id": f"txn_{sequence:04d}",
        "account_id": account_id,
        "occurred_at": occurred.isoformat().replace("+00:00", "Z"),
        "merchant": merchant,
        "description": description,
        "amount": amount,
        "currency": "CNY",
        "direction": direction,
        "category": category,
        "status": "POSTED",
    }


def build_regression_transactions() -> list[dict[str, object]]:
    rng = Random(SEED)
    rows: list[dict[str, object]] = []
    start = date(2026, 6, 3)
    end = date(2026, 9, 20)

    def add(**values: object) -> None:
        rows.append(transaction(len(rows) + 1, **values))  # type: ignore[arg-type]

    for month in (6, 7, 8, 9):
        add(
            account_id="acc_salary",
            day=date(2026, month, 5),
            merchant="星河科技（虚构）",
            description="月度工资",
            amount="23800.00",
            direction="CREDIT",
            category="SALARY",
        )
        add(
            account_id="acc_salary",
            day=date(2026, month, 3),
            merchant="青禾公寓（虚构）",
            description="月租",
            amount="6200.00",
            direction="DEBIT",
            category="HOUSING",
        )
        for merchant, amount, billing_day in (
            ("星幕视频", "28.00", 8),
            ("海浪音乐", "15.00", 12),
            ("云笺存储", "18.00", 16),
            ("像素设计", "88.00", 20),
        ):
            add(
                account_id="acc_credit",
                day=date(2026, month, billing_day),
                merchant=merchant,
                description="固定订阅",
                amount=amount,
                direction="DEBIT",
                category="SUBSCRIPTION",
            )

    current = start
    food_index = 0
    while current <= end:
        amount = f"{rng.choice([26, 32, 38, 45, 58, 76])}.{rng.choice([0, 5]):02d}"
        add(
            account_id="acc_salary",
            day=current,
            merchant=rng.choice(["青苗餐厅", "拾味食堂", "暖食外卖"]),
            description="日常餐饮" if current.month != 8 else "八月餐饮支出",
            amount=amount,
            direction="DEBIT",
            category="FOOD",
        )
        food_index += 1
        current += timedelta(days=3)

    for extra_day in (2, 6, 10, 14, 18, 22, 26, 30):
        add(
            account_id="acc_salary",
            day=date(2026, 8, extra_day),
            merchant="暖食外卖",
            description="八月额外外卖",
            amount=f"{48 + extra_day}.00",
            direction="DEBIT",
            category="FOOD",
        )

    current = start + timedelta(days=1)
    while current <= end:
        add(
            account_id="acc_salary",
            day=current,
            merchant=rng.choice(["城市地铁", "清风出行"]),
            description="通勤交通",
            amount=f"{rng.choice([6, 8, 12, 18, 24])}.00",
            direction="DEBIT",
            category="TRANSPORT",
        )
        current += timedelta(days=4)

    for month in (6, 7, 8):
        for day, merchant, amount in (
            (10, "江城电力", "126.80"),
            (15, "蓝波水务", "43.20"),
            (25, "星联通信", "99.00"),
        ):
            add(
                account_id="acc_salary",
                day=date(2026, month, day),
                merchant=merchant,
                description="水电通信费",
                amount=amount,
                direction="DEBIT",
                category="UTILITIES",
            )

    for offset, amount in enumerate(
        (
            "188.00",
            "329.00",
            "516.00",
            "268.00",
            "899.00",
            "145.00",
            "4200.00",
            "236.00",
        )
    ):
        add(
            account_id="acc_credit",
            day=start + timedelta(days=8 + offset * 12),
            merchant="山河商城",
            description="日常购物" if amount != "4200.00" else "家用电器（大额）",
            amount=amount,
            direction="DEBIT",
            category="SHOPPING",
        )

    for day, amount, description in (
        (4, "680.00", "往返交通"),
        (5, "1280.00", "酒店"),
        (6, "360.00", "景区门票"),
        (7, "420.00", "旅行餐饮"),
        (8, "980.00", "酒店续住"),
        (9, "540.00", "返程交通"),
    ):
        add(
            account_id="acc_travel",
            day=date(2026, 8, day),
            merchant="远山旅行",
            description=description,
            amount=amount,
            direction="DEBIT",
            category="TRAVEL",
        )

    for offset in range(6):
        add(
            account_id="acc_credit",
            day=start + timedelta(days=15 + offset * 16),
            merchant="森林影城",
            description="电影与休闲",
            amount="68.00",
            direction="DEBIT",
            category="ENTERTAINMENT",
        )

    for day, amount in (
        (date(2026, 6, 22), "86.00"),
        (date(2026, 7, 19), "320.00"),
        (date(2026, 9, 11), "1580.00"),
    ):
        add(
            account_id="acc_salary",
            day=day,
            merchant="康和健康",
            description="医疗健康",
            amount=amount,
            direction="DEBIT",
            category="HEALTH",
        )

    for day, amount, direction, account_id in (
        (date(2026, 6, 18), "3000.00", "DEBIT", "acc_salary"),
        (date(2026, 6, 18), "3000.00", "CREDIT", "acc_savings"),
        (date(2026, 7, 18), "5000.00", "DEBIT", "acc_salary"),
        (date(2026, 7, 18), "5000.00", "CREDIT", "acc_savings"),
        (date(2026, 9, 2), "2000.00", "DEBIT", "acc_savings"),
        (date(2026, 9, 2), "2000.00", "CREDIT", "acc_travel"),
    ):
        add(
            account_id=account_id,
            day=day,
            merchant="本人账户",
            description="账户间转账",
            amount=amount,
            direction=direction,
            category="TRANSFER",
        )

    for offset, amount in enumerate(("32.00", "55.00", "120.00")):
        add(
            account_id="acc_salary",
            day=date(2026, 7, 7) + timedelta(days=offset * 29),
            merchant="社区服务中心",
            description="其他支出",
            amount=amount,
            direction="DEBIT",
            category="OTHER",
        )

    return sorted(
        rows, key=lambda item: (str(item["occurred_at"]), str(item["transaction_id"]))
    )


def build_transactions() -> list[dict[str, object]]:
    """Keep established June–September goldens; extend with seeded historical facts."""
    rows = build_regression_transactions()
    rng = Random(SEED + 93)
    cutoff = date(2026, 10, 7)

    def add(
        day: date,
        merchant: str,
        amount: str,
        category: str,
        *,
        account: str = "acc_salary",
        direction: str = "DEBIT",
        description: str = "模拟历史账单",
        status: str = "POSTED",
        minute: int = 0,
    ) -> None:
        if day > cutoff:
            return
        row = transaction(
            len(rows) + 10000,
            account_id=account,
            day=day,
            merchant=merchant,
            description=description,
            amount=amount,
            direction=direction,
            category=category,
        )
        row["transaction_id"] = f"txn_history_{len(rows):05d}"
        row["status"] = status
        row["occurred_at"] = (
            datetime(day.year, day.month, day.day, 12, minute, tzinfo=UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )
        rows.append(row)

    # Explicit detected-only alias/price-change evidence retained from the original fixture.
    for index, (month, merchant, amount) in enumerate(
        [(4, "晨光健身", "99.00"), (5, "晨光健身*月卡", "109.00")], 1
    ):
        row = transaction(
            9000 + index,
            account_id="acc_credit",
            day=date(2025, month, 25),
            merchant=merchant,
            description="月度会员扣费",
            amount=amount,
            direction="DEBIT",
            category="HEALTH",
        )
        row["transaction_id"] = f"txn_sub_detect_{index:02d}"
        row["occurred_at"] = f"2025-{month:02d}-25T12:00:00Z"
        rows.append(row)

    for year in (2025, 2026):
        for month in range(1, 13):
            if date(year, month, 1) > cutoff or (
                year == 2026 and month in (6, 7, 8, 9)
            ):
                continue
            ordinal = (year - 2025) * 12 + month
            salary = 20500 if year == 2025 else 23800
            rent = 5700 if year == 2025 else 6200
            add(
                date(year, month, 5),
                "星河科技（虚构）",
                f"{salary}.00",
                "SALARY",
                direction="CREDIT",
                description="月度工资",
            )
            add(
                date(year, month, 3),
                "青禾公寓（虚构）",
                f"{rent}.00",
                "HOUSING",
                description="月租",
            )
            if month in (1, 6, 12):
                add(
                    date(year, month, 18),
                    "星河科技（虚构）",
                    "8000.00",
                    "BONUS",
                    direction="CREDIT",
                    description="季度或年终奖金",
                )
            for merchant, amount, day in [
                ("星幕视频", "28.00", 8),
                ("海浪音乐", "15.00", 12),
                ("云笺存储", "18.00", 16),
                ("像素设计", "58.00" if ordinal < 15 else "88.00", 20),
            ]:
                add(
                    date(year, month, day),
                    merchant,
                    amount,
                    "SUBSCRIPTION",
                    account="acc_credit",
                    description="固定订阅（历史套餐费用）",
                )
            for day in range(1, monthrange(year, month)[1] + 1):
                current = date(year, month, day)
                if day % 2:
                    cents = rng.choice([2600, 3200, 3800, 4505, 5800, 7600, 9800])
                    add(
                        current,
                        rng.choice(["青苗餐厅", "拾味食堂", "暖食外卖"]),
                        f"{Decimal(cents) / 100:.2f}",
                        "FOOD",
                        description="日常餐饮",
                    )
                if current.weekday() < 5:
                    add(
                        current,
                        "城市地铁",
                        f"{rng.choice([6, 8, 12])}.00",
                        "TRANSPORT",
                        description="工作日通勤",
                    )
                if day in (6, 13, 20, 27):
                    add(
                        current,
                        "禾田生鲜",
                        f"{rng.randint(85, 260)}.00",
                        "FOOD",
                        account="acc_credit",
                        description="家庭生鲜采购",
                    )
            for merchant, category, amount, day in [
                (
                    "江城电力",
                    "UTILITIES",
                    "208.80" if month in (1, 2, 7, 8) else "126.80",
                    10,
                ),
                ("蓝波水务", "UTILITIES", "43.20", 15),
                ("星联通信", "UTILITIES", "99.00", 25),
                ("山河商城", "SHOPPING", f"{rng.randint(100, 850)}.00", 22),
                ("康和健康", "HEALTH", "86.00", 19),
                ("森林影城", "ENTERTAINMENT", "68.00", 24),
                ("社区服务中心", "OTHER", "32.00", 7),
            ]:
                add(date(year, month, day), merchant, amount, category)
            if month in (2, 5, 8, 10):
                for day, amount in [(2, "680.00"), (3, "1280.00"), (4, "360.00")]:
                    add(
                        date(year, month, day),
                        "远山旅行",
                        amount,
                        "TRAVEL",
                        account="acc_travel",
                        description="节假日旅行",
                    )
            add(
                date(year, month, 18),
                "本人账户",
                "3000.00",
                "TRANSFER",
                description="储蓄划转",
            )
            add(
                date(year, month, 18),
                "本人账户",
                "3000.00",
                "TRANSFER",
                account="acc_savings",
                direction="CREDIT",
                description="储蓄划入",
            )
            add(
                date(year, month, 26),
                "山河商城",
                "120.00",
                "REFUND",
                account="acc_credit",
                direction="CREDIT",
                description="购物退货退款",
            )
            # Non-posted records must not inflate analytics or anomaly evidence.
            add(
                date(year, month, 28),
                "山河商城",
                "499.00",
                "SHOPPING",
                status="REVERSED",
                description="已撤销订单",
            )
            add(
                date(year, month, 29 if month != 2 else 28),
                "清风出行",
                "35.00",
                "TRANSPORT",
                status="PENDING",
                description="待入账出行",
            )

    # Complete the latest period and cover real anomaly rules without changing August goldens.
    for day in range(21, 31):
        add(date(2026, 9, day), "拾味食堂", "45.05", "FOOD", description="月末日常餐饮")
        add(date(2026, 9, day), "城市地铁", "8.00", "TRANSPORT", description="月末通勤")
    for minute in (0, 3, 6):
        add(
            date(2026, 10, 6),
            "晨雾数码（虚构）",
            "999.00",
            "SHOPPING",
            account="acc_credit",
            minute=minute,
            description="短时重复扣费测试样例",
        )
    add(
        date(2026, 10, 7),
        "远帆家居（虚构）",
        "8600.00",
        "SHOPPING",
        account="acc_credit",
        description="新商户大额消费测试样例",
    )
    return sorted(
        rows, key=lambda item: (str(item["occurred_at"]), str(item["transaction_id"]))
    )


def main() -> None:
    write(
        "accounts.json",
        [
            {
                "account_id": "acc_salary",
                "display_name": "工资卡",
                "account_type": "DEBIT",
                "masked_number": "****6688",
                "currency": "CNY",
                "status": "ACTIVE",
                "balance": "23864.52",
            },
            {
                "account_id": "acc_savings",
                "display_name": "储蓄卡",
                "account_type": "SAVINGS",
                "masked_number": "****1024",
                "currency": "CNY",
                "status": "ACTIVE",
                "balance": "78620.00",
            },
            {
                "account_id": "acc_credit",
                "display_name": "信用卡",
                "account_type": "CREDIT",
                "masked_number": "****9527",
                "currency": "CNY",
                "status": "ACTIVE",
                "balance": "-4860.35",
            },
            {
                "account_id": "acc_travel",
                "display_name": "旅行卡",
                "account_type": "DEBIT",
                "masked_number": "****3366",
                "currency": "CNY",
                "status": "ACTIVE",
                "balance": "12680.40",
            },
        ],
    )
    write("transactions.json", build_transactions())
    write(
        "payees.json",
        [
            {
                "payee_id": "payee_001",
                "display_name": "张三",
                "bank_name": "星河银行（虚构）",
                "masked_account": "****2231",
                "phone_alias": "手机尾号 1001",
            },
            {
                "payee_id": "payee_002",
                "display_name": "张三",
                "bank_name": "蓝海银行（虚构）",
                "masked_account": "****9102",
                "phone_alias": "手机尾号 1002",
            },
            {
                "payee_id": "payee_003",
                "display_name": "李小雨",
                "bank_name": "星河银行（虚构）",
                "masked_account": "****4815",
                "phone_alias": "手机尾号 1003",
            },
            {
                "payee_id": "payee_004",
                "display_name": "王海",
                "bank_name": "森林银行（虚构）",
                "masked_account": "****7716",
                "phone_alias": "手机尾号 1004",
            },
            {
                "payee_id": "payee_005",
                "display_name": "青禾物业",
                "bank_name": "蓝海银行（虚构）",
                "masked_account": "****3308",
                "phone_alias": "服务号尾号 2001",
            },
            {
                "payee_id": "payee_006",
                "display_name": "陈晨",
                "bank_name": "远山银行（虚构）",
                "masked_account": "****6054",
                "phone_alias": "手机尾号 1006",
            },
        ],
    )
    write(
        "subscriptions.json",
        [
            {
                "subscription_id": "sub_video",
                "merchant": "星幕视频",
                "plan_name": "标准会员",
                "amount": "28.00",
                "currency": "CNY",
                "billing_interval": "MONTHLY",
                "next_billing_at": "2026-10-08T12:00:00Z",
                "status": "ACTIVE",
                "cancellable": True,
                "resumption_supported": True,
                "cancellation_supported": True,
            },
            {
                "subscription_id": "sub_music",
                "merchant": "海浪音乐",
                "plan_name": "个人会员",
                "amount": "15.00",
                "currency": "CNY",
                "billing_interval": "MONTHLY",
                "next_billing_at": "2026-10-12T12:00:00Z",
                "status": "ACTIVE",
                "cancellable": True,
                "resumption_supported": True,
                "cancellation_supported": True,
            },
            {
                "subscription_id": "sub_cloud",
                "merchant": "云笺存储",
                "plan_name": "50 GB",
                "amount": "18.00",
                "currency": "CNY",
                "billing_interval": "MONTHLY",
                "next_billing_at": "2026-10-16T12:00:00Z",
                "status": "ACTIVE",
                "cancellable": True,
                "resumption_supported": True,
                "cancellation_supported": True,
            },
            {
                "subscription_id": "sub_design",
                "merchant": "像素设计",
                "plan_name": "专业版",
                "amount": "88.00",
                "currency": "CNY",
                "billing_interval": "MONTHLY",
                "next_billing_at": "2026-10-20T12:00:00Z",
                "status": "ACTIVE",
                "cancellable": True,
                "resumption_supported": True,
                "cancellation_supported": True,
            },
            {
                "subscription_id": "sub_fitness",
                "merchant": "活力健身",
                "plan_name": "月卡",
                "amount": "128.00",
                "currency": "CNY",
                "billing_interval": "MONTHLY",
                "next_billing_at": None,
                "status": "CANCELLED",
                "cancellable": False,
                "resumption_supported": True,
                "cancellation_supported": True,
            },
        ],
    )


if __name__ == "__main__":
    main()
