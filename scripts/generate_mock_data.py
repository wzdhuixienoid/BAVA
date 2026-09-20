"""Generate the committed deterministic synthetic banking fixtures."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from random import Random

SEED = 20260920
DATA_DIR = (
    Path(__file__).parents[1] / "apps/api/src/banking_api/mock_bank/data"
)


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


def build_transactions() -> list[dict[str, object]]:
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

    for offset, amount in enumerate(("188.00", "329.00", "516.00", "268.00", "899.00", "145.00", "4200.00", "236.00")):
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

    for day, amount in ((date(2026, 6, 22), "86.00"), (date(2026, 7, 19), "320.00"), (date(2026, 9, 11), "1580.00")):
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

    return sorted(rows, key=lambda item: (str(item["occurred_at"]), str(item["transaction_id"])))


def main() -> None:
    write(
        "accounts.json",
        [
            {"account_id": "acc_salary", "display_name": "工资卡", "account_type": "DEBIT", "masked_number": "****6688", "currency": "CNY", "status": "ACTIVE", "balance": "23864.52"},
            {"account_id": "acc_savings", "display_name": "储蓄卡", "account_type": "SAVINGS", "masked_number": "****1024", "currency": "CNY", "status": "ACTIVE", "balance": "78620.00"},
            {"account_id": "acc_credit", "display_name": "信用卡", "account_type": "CREDIT", "masked_number": "****9527", "currency": "CNY", "status": "ACTIVE", "balance": "-4860.35"},
            {"account_id": "acc_travel", "display_name": "旅行卡", "account_type": "DEBIT", "masked_number": "****3366", "currency": "CNY", "status": "ACTIVE", "balance": "12680.40"},
        ],
    )
    write("transactions.json", build_transactions())
    write(
        "payees.json",
        [
            {"payee_id": "payee_001", "display_name": "张三", "bank_name": "星河银行（虚构）", "masked_account": "****2231", "phone_alias": "手机尾号 1001"},
            {"payee_id": "payee_002", "display_name": "张三", "bank_name": "蓝海银行（虚构）", "masked_account": "****9102", "phone_alias": "手机尾号 1002"},
            {"payee_id": "payee_003", "display_name": "李小雨", "bank_name": "星河银行（虚构）", "masked_account": "****4815", "phone_alias": "手机尾号 1003"},
            {"payee_id": "payee_004", "display_name": "王海", "bank_name": "森林银行（虚构）", "masked_account": "****7716", "phone_alias": "手机尾号 1004"},
            {"payee_id": "payee_005", "display_name": "青禾物业", "bank_name": "蓝海银行（虚构）", "masked_account": "****3308", "phone_alias": "服务号尾号 2001"},
            {"payee_id": "payee_006", "display_name": "陈晨", "bank_name": "远山银行（虚构）", "masked_account": "****6054", "phone_alias": "手机尾号 1006"},
        ],
    )
    write(
        "subscriptions.json",
        [
            {"subscription_id": "sub_video", "merchant": "星幕视频", "monthly_amount": "28.00", "currency": "CNY", "billing_day": 8, "status": "ACTIVE", "last_used_at": "2026-09-18T12:00:00Z"},
            {"subscription_id": "sub_music", "merchant": "海浪音乐", "monthly_amount": "15.00", "currency": "CNY", "billing_day": 12, "status": "ACTIVE", "last_used_at": "2026-09-19T08:00:00Z"},
            {"subscription_id": "sub_cloud", "merchant": "云笺存储", "monthly_amount": "18.00", "currency": "CNY", "billing_day": 16, "status": "ACTIVE", "last_used_at": "2025-11-03T10:00:00Z"},
            {"subscription_id": "sub_design", "merchant": "像素设计", "monthly_amount": "88.00", "currency": "CNY", "billing_day": 20, "status": "ACTIVE", "last_used_at": "2026-06-12T09:00:00Z"},
            {"subscription_id": "sub_fitness", "merchant": "活力健身", "monthly_amount": "128.00", "currency": "CNY", "billing_day": 3, "status": "CANCELLED", "last_used_at": "2026-03-20T18:00:00Z"},
        ],
    )


if __name__ == "__main__":
    main()
