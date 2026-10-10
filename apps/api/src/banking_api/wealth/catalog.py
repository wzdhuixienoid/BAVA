"""Idempotent fixtures; hash conflicts fail closed rather than changing historical terms."""

import hashlib
import json
import random
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select

from banking_api.wealth.calculation import CN, UNIT, WealthError
from banking_api.wealth.models import WealthDocument, WealthNav, WealthProduct, WealthProductVersion

PRODUCTS = [
    ("演示稳享日日", 1, "100", [0, 1, 2, 3, 4], "0", "0"),
    ("演示稳享周周", 2, "1000", [0], "0", "0.001"),
    ("演示稳健优选", 2, "1000", [0, 1, 2, 3, 4], "0.001", "0.001"),
    ("演示均衡优选", 3, "1000", [0, 1, 2, 3, 4], "0.002", "0.001"),
    ("演示均衡周享", 3, "1000", [0], "0.002", "0.002"),
    ("演示进取成长", 4, "1000", [0, 1, 2, 3, 4], "0.003", "0.002"),
    ("演示进取周享", 4, "5000", [4], "0.003", "0.003"),
    ("演示高波动精选", 5, "1000", [0, 1, 2, 3, 4], "0.005", "0.005"),
]


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def generated_navs(product_id, risk):
    rng = random.Random(f"wealth-fixture-v1:{product_id}")
    day, nav = date(2025, 1, 1), Decimal("1")
    while day <= date(2027, 12, 31):
        if day.weekday() < 5:
            delta = Decimal(rng.randint(-40 * risk, 42 * risk)) / Decimal(100000)
            nav = max(UNIT, (nav * (1 + delta)).quantize(UNIT))
            yield day, nav, datetime.combine(day, time(18), CN)
        day += timedelta(days=1)


async def seed_catalog(session):
    effective = datetime(2025, 1, 1, tzinfo=UTC)
    for index, (name, risk, minimum, weekdays, buy, sell) in enumerate(PRODUCTS, 1):
        pid, vid = f"mock-wealth-{index:02}", f"mock-wealth-{index:02}:v1"
        open_label = "每个模拟交易日" if len(weekdays) == 5 else f"每周{'一二三四五'[weekdays[0]]}"
        sections = {
            "说明书": (
                f"{name}（模拟），开放式净值型，人民币。风险 R{risk}，起购总金额 {minimum} 元。"
                f"开放安排：{open_label}，北京时间严格早于15:00受理当日交易。"
                f"申购费率 {Decimal(buy) * 100}%、赎回费率 {Decimal(sell) * 100}%。"
                "不另收持续管理费。"
            ),
            "风险揭示": (
                "模拟产品无本金或收益保证，净值可能上涨或下跌。"
                "模拟历史指标不代表未来收益。必须保本或不接受损失者不适合所有模拟产品。"
            ),
            "交易FAQ": (
                "申购／购买与赎回／卖出都需确认及强验证。按绑定的未来交易日净值成交，核对金额"
                "仅为估算。交易日18:00发布净值，下一模拟交易日10:00确认成交。申购确"
                "认时入账份额；赎回确认后的下一模拟交易日10:00到账。模拟交易日仅周一至周"
                "五，不处理真实节假日。受理后不可撤单。"
            ),
        }
        terms = {
            "document_hashes": {
                f"{pid}:v1:{n}": digest(c) for n, c in enumerate(sections.values(), 1)
            },
            "sale_status": "ON_SALE",
            "currency": "CNY",
            "minimum": minimum,
            "weekdays": weekdays,
            "cutoff": "15:00",
            "purchase_rate": buy,
            "redeem_rate": sell,
            "document_version": "v1",
            "management_rate": "0",
            "pricing": "future_trade_date_nav",
            "confirm": "next_weekday_10",
            "settle": "purchase_at_confirm_redeem_next_weekday_10",
        }
        fact = {"name": name, "risk": f"R{risk}", "terms": terms}
        existing = await session.get(WealthProductVersion, vid)
        if existing and (
            existing.content_hash != digest(fact)
            or existing.terms != terms
            or existing.name != name
            or existing.risk != f"R{risk}"
        ):
            raise WealthError("FIXTURE_CONFLICT", "已存在产品版本与导入内容不同，禁止覆盖")
        if not await session.get(WealthProduct, pid):
            session.add(WealthProduct(product_id=pid, current_version=vid))
            await session.flush()
        if not existing:
            session.add(
                WealthProductVersion(
                    version_id=vid,
                    product_id=pid,
                    version="v1",
                    name=name,
                    risk=f"R{risk}",
                    terms=terms,
                    content_hash=digest(fact),
                    effective_from=effective,
                )
            )
            await session.flush()
        for n, (section, content) in enumerate(sections.items(), 1):
            did = f"{pid}:v1:{n}"
            doc = await session.get(WealthDocument, did)
            if doc and (
                doc.content_hash != digest(content)
                or doc.structured_terms != terms
                or doc.content != content
                or doc.source != f"/api/v1/wealth/documents/{did}"
                or doc.version_id != vid
                or doc.version != "v1"
                or doc.section != section
            ):
                raise WealthError("FIXTURE_CONFLICT", "已存在资料版本与导入内容不同，禁止覆盖")
            if not doc:
                session.add(
                    WealthDocument(
                        document_id=did,
                        product_id=pid,
                        version_id=vid,
                        version="v1",
                        source=f"/api/v1/wealth/documents/{did}",
                        section=section,
                        effective_from=effective,
                        content_hash=digest(content),
                        content=content,
                        structured_terms=terms,
                    )
                )
        navs = {
            n.nav_date: n
            for n in (
                await session.scalars(select(WealthNav).where(WealthNav.product_id == pid))
            ).all()
        }
        for day, nav, published in generated_navs(pid, risk):
            old = navs.get(day)
            if old and (
                old.nav != nav or old.published_at.replace(tzinfo=UTC) != published.astimezone(UTC)
            ):
                raise WealthError("FIXTURE_CONFLICT", "已存在净值与导入内容不同，禁止覆盖")
            if not old:
                session.add(
                    WealthNav(
                        product_id=pid,
                        nav_date=day,
                        nav=nav,
                        published_at=published.astimezone(UTC),
                    )
                )
    await session.flush()
