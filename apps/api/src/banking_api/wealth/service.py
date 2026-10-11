import calendar
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, or_, select

from banking_api.wealth.calculation import CENT, WealthError, schedule, utc
from banking_api.wealth.catalog import digest
from banking_api.wealth.models import (
    WealthAssessment,
    WealthDocument,
    WealthHold,
    WealthNav,
    WealthOrder,
    WealthPosition,
    WealthProduct,
    WealthProductVersion,
)
from banking_api.wealth.schemas import (
    WealthAssessmentResult,
    WealthOrderResult,
    WealthPositionResult,
    WealthProductResult,
    WealthRecommendationResult,
)

QUESTIONNAIRE_VERSION = "mock-v1"
RULES_VERSION = "mock-v1"

QUESTIONS = [
    ("产品理解", "完全不了解／略知／理解基本风险／理解净值与费用／能够理解复杂风险"),
    ("投资经验", "无／不足一年／1–3 年／3–5 年／5 年以上"),
    ("收入稳定性", "无稳定收入／波动很大／一般／较稳定／稳定且来源多样"),
    ("应急资金", "无／不足一个月／1–3 个月／3–6 个月／超过 6 个月"),
    ("投资目标", "必须保本／保守／稳健／均衡／进取"),
    ("可接受本金损失", "不接受／不超过 1%／不超过 3%／不超过 10%／可接受超过 10%"),
    ("下跌时的选择", "立即退出／大部分退出／视情况减持／持有观察／接受波动继续持有"),
    ("投资期限", "不足一周／不足一月／1–3 个月／3–12 个月／一年以上"),
]


def assess(answers):
    score = sum(answers)
    grade = 1 if score <= 6 else 2 if score <= 12 else 3 if score <= 19 else 4 if score <= 25 else 5
    reasons = []
    suitable = answers[4] != 0 and answers[5] != 0
    if not suitable:
        reasons.append("要求保本或不接受本金损失，所有模拟净值型产品均不适合")
    if 1 <= answers[5] <= 3:
        if grade > answers[5]:
            reasons.append(f"损失承受能力将等级限制为 C{answers[5]}")
        grade = min(grade, answers[5])
    return score, grade, suitable, reasons


class WealthService:
    def __init__(self, session, balances=None, clock=lambda: datetime.now(UTC)):
        self.session, self.balances, self.clock = session, balances, clock

    async def current_assessment(self, user_id):
        return await self.session.scalar(
            select(WealthAssessment)
            .where(WealthAssessment.user_id == user_id, WealthAssessment.invalidated_at.is_(None))
            .order_by(WealthAssessment.created_at.desc(), WealthAssessment.assessment_id.desc())
            .limit(1)
        )

    def assessment_result(self, model):
        return WealthAssessmentResult(
            assessment_id=model.assessment_id,
            grade_display=f"C{model.grade}（Mock 测评）",
            score=model.score,
            reasons=model.reasons,
            suitable=model.suitable,
            expires_at=utc(model.expires_at),
            expired=(
                utc(model.expires_at) <= utc(self.clock())
                or model.invalidated_at is not None
                or model.questionnaire_version != QUESTIONNAIRE_VERSION
                or model.rules_version != RULES_VERSION
            ),
            questionnaire_version=model.questionnaire_version,
            rules_version=model.rules_version,
        )

    async def save_assessment(self, user_id, body):
        score, grade, suitable, reasons = assess(body.answers)
        now = utc(self.clock())
        # True calendar 12 months, including leap day.
        expiry = now.replace(
            year=now.year + 1, day=min(now.day, calendar.monthrange(now.year + 1, now.month)[1])
        )
        old = await self.current_assessment(user_id)
        if old:
            old.invalidated_at = now
        model = WealthAssessment(
            user_id=user_id,
            answers=body.answers,
            score=score,
            grade=grade,
            suitable=suitable,
            reasons=reasons,
            questionnaire_version=body.questionnaire_version,
            rules_version=RULES_VERSION,
            created_at=now,
            expires_at=expiry,
        )
        self.session.add(model)
        await self.session.flush()
        return self.assessment_result(model)

    async def require_assessment(self, user_id, risk=None):
        model = await self.current_assessment(user_id)
        if not model:
            raise WealthError("ASSESSMENT_REQUIRED", "请先完成风险测评")
        if (
            utc(model.expires_at) <= utc(self.clock())
            or model.invalidated_at is not None
            or model.questionnaire_version != QUESTIONNAIRE_VERSION
            or model.rules_version != RULES_VERSION
        ):
            raise WealthError("ASSESSMENT_EXPIRED", "风险测评已失效，请重新测评")
        if not model.suitable:
            raise WealthError("SUITABILITY_MISMATCH", "；".join(model.reasons))
        if risk and model.grade < int(risk[1]):
            raise WealthError("SUITABILITY_MISMATCH", "该产品不符合您的风险承受能力")
        return model

    async def version(self, product_id, version_id=None):
        product = await self.session.get(WealthProduct, product_id)
        if not product:
            raise WealthError("NOT_FOUND", "未找到该模拟产品")
        version = await self.session.get(
            WealthProductVersion, version_id or product.current_version
        )
        if not version or version.product_id != product_id:
            raise WealthError("NOT_FOUND", "未找到产品资料版本")
        return version

    async def documents(self, version, historical=False):
        stmt = select(WealthDocument).where(WealthDocument.version_id == version.version_id)
        if not historical:
            stmt = stmt.where(
                WealthDocument.effective_from <= utc(self.clock()),
                or_(
                    WealthDocument.effective_to.is_(None),
                    WealthDocument.effective_to > utc(self.clock()),
                ),
            )
        return list((await self.session.scalars(stmt.order_by(WealthDocument.document_id))).all())

    async def healthy(self, version):
        docs = await self.documents(version)
        fact = {"name": version.name, "risk": version.risk, "terms": version.terms}
        return (
            len(docs) >= 3
            and digest(fact) == version.content_hash
            and all(
                d.structured_terms == version.terms
                and d.content_hash == digest(d.content)
                and d.version == version.terms["document_version"]
                and version.terms.get("document_hashes", {}).get(d.document_id) == d.content_hash
                and d.source == f"/api/v1/wealth/documents/{d.document_id}"
                for d in docs
            )
        )

    async def nav(self, product_id, day=None):
        stmt = select(WealthNav).where(
            WealthNav.product_id == product_id, WealthNav.published_at <= utc(self.clock())
        )
        if day:
            stmt = stmt.where(WealthNav.nav_date == day)
        return await self.session.scalar(stmt.order_by(WealthNav.nav_date.desc()).limit(1))

    async def validate_purchase(self, user_id, version, amount, account_id):
        assessment = await self.require_assessment(user_id, version.risk)
        if not await self.healthy(version):
            raise WealthError("PRODUCT_DOCUMENT_CONFLICT", "产品资料异常，暂不能申购")
        if (
            version.terms["sale_status"] != "ON_SALE"
            or utc(version.effective_from) > utc(self.clock())
            or (version.effective_to and utc(version.effective_to) <= utc(self.clock()))
        ):
            raise WealthError("PRODUCT_NOT_TRADABLE", "该产品当前不可申购")
        if amount < Decimal(version.terms["minimum"]):
            raise WealthError("BELOW_MINIMUM", "申购总金额低于起购金额")
        if not await self.nav(version.product_id):
            raise WealthError("NAV_MISSING", "缺少已发布净值，暂不能交易")
        if await self.balances.in_session(self.session, user_id, account_id) < amount:
            raise WealthError("INSUFFICIENT_FUNDS", "账户可用余额不足")
        return assessment

    async def product(self, product_id, user_id=None):
        v = await self.version(product_id)
        nav = await self.nav(product_id)
        docs = await self.documents(v)
        change = drawdown = None
        missing = "暂无已发布净值" if not nav else "模拟历史不足30日，暂无数据"
        if nav:
            rows = list(
                (
                    await self.session.scalars(
                        select(WealthNav)
                        .where(
                            WealthNav.product_id == product_id,
                            WealthNav.published_at <= utc(self.clock()),
                            WealthNav.nav_date >= nav.nav_date - timedelta(days=35),
                        )
                        .order_by(WealthNav.nav_date)
                    )
                ).all()
            )
            anchors = [n for n in rows if n.nav_date <= nav.nav_date - timedelta(days=30)]
            if anchors:
                anchor = anchors[-1]
                series = [n.nav for n in rows if n.nav_date >= anchor.nav_date]
                peak, worst = series[0], Decimal(0)
                for value in series:
                    peak = max(peak, value)
                    worst = max(worst, (peak - value) / peak)
                percent = ((nav.nav / anchor.nav - 1) * 100).quantize(CENT, ROUND_HALF_UP)
                change = f"{percent:.2f}%（模拟历史）"
                drawdown = f"{(worst * 100).quantize(CENT, ROUND_HALF_UP):.2f}%（模拟历史）"
                missing = None
        days = v.terms["weekdays"]
        allowed, reason = False, "请先完成风险测评"
        if user_id:
            try:
                await self.require_assessment(user_id, v.risk)
                allowed, reason = True, None
            except WealthError as exc:
                reason = str(exc)
        documents_ok = await self.healthy(v)
        sale_open = (
            v.terms["sale_status"] == "ON_SALE"
            and utc(v.effective_from) <= utc(self.clock())
            and (v.effective_to is None or utc(v.effective_to) > utc(self.clock()))
        )
        tradable = bool(nav) and documents_ok and sale_open
        if not documents_ok:
            reason = "产品资料异常，禁止新申购"
        elif not nav:
            reason = "缺少已发布净值，暂不能申购"
        elif not sale_open:
            reason = "产品当前不可交易"
        from banking_api.wealth.availability import feature_status

        if not feature_status()["new_business_allowed"]:
            allowed, reason = False, "已暂停新理财交易"
        return WealthProductResult(
            purchase_allowed=allowed and tradable,
            purchase_block_reason=reason,
            product_id=product_id,
            version_id=v.version_id,
            name=v.name,
            risk=v.risk,
            minimum_display=f"{Decimal(v.terms['minimum']):,.2f} 元",
            open_display="每个模拟交易日 15:00前"
            if len(days) == 5
            else f"每周{'一二三四五'[days[0]]} 15:00前",
            fees_display=(
                f"申购 {Decimal(v.terms['purchase_rate']) * 100:.2f}% / "
                f"赎回 {Decimal(v.terms['redeem_rate']) * 100:.2f}%"
            ),
            nav_display=f"{nav.nav:.6f}" if nav else None,
            nav_date=nav.nav_date.isoformat() if nav else None,
            change_display=change,
            drawdown_display=drawdown,
            missing_reason=missing,
            sources=[d.source for d in docs],
            tradable=tradable,
            terms=v.terms,
        )

    async def products(self, user_id=None):
        ids = (
            await self.session.scalars(
                select(WealthProduct.product_id).order_by(WealthProduct.product_id)
            )
        ).all()
        return [await self.product(pid, user_id) for pid in ids]

    async def compare(self, ids, user_id=None):
        if not 1 <= len(ids) <= 4 or len(set(ids)) != len(ids):
            raise WealthError("COMPARE_LIMIT", "请选择1至4个不同产品")
        return [await self.product(pid, user_id) for pid in ids]

    async def recommend(self, user_id, body, *, constraints=None, priority="RISK"):
        a = await self.require_assessment(user_id)
        from banking_api.wealth.calculation import quantity

        amount = quantity(body.amount) if body.amount else None
        if body.account_id:
            self.balances._bank.get_balance(body.account_id, user_id=user_id)
        funds = (
            await self.balances.in_session(self.session, user_id, body.account_id)
            if body.account_id
            else None
        )
        from banking_api.wealth.requirements import parse_requirements

        constraints = constraints or parse_requirements(body.needs)
        ranked, excluded = [], {}
        for p in await self.products(user_id):
            reasons = []
            if not p.tradable:
                reasons.append("不在售、资料异常或净值缺失")
            if int(p.risk[1]) > a.grade:
                reasons.append("超过客户风险等级")
            if amount and amount < Decimal(p.terms["minimum"]):
                reasons.append("低于起购总金额")
            if amount and funds is not None and amount > funds:
                reasons.append("账户可用余额不足")
            risk = int(p.risk[1])
            if (
                constraints.ambiguous
                or constraints.principal_guarantee
                or constraints.no_principal_loss
                or constraints.immediate_cash
            ):
                reasons.extend(
                    constraints.reasons or ["本次保本、损失或流动性条件与净值型产品不适配"]
                )
            if risk in constraints.excluded_risks or risk > constraints.maximum_risk:
                reasons.append("不符合本次明确风险偏好或排除条件")
            if (constraints.within_week or constraints.avoid_weekly) and len(
                p.terms["weekdays"]
            ) < 5:
                reasons.append("一周内可能用钱，排除周开放产品")
            if reasons:
                excluded[p.product_id] = reasons
            else:
                preferred = constraints.preferred_risk or a.answers[4]
                risk = int(p.risk[1])
                day = schedule(self.clock(), p.terms["weekdays"], "PURCHASE")["trade_date"]
                fee = Decimal(p.terms["purchase_rate"]) + Decimal(p.terms["redeem_rate"])
                rank = (abs(risk - preferred), risk, day, fee, p.product_id)
                if priority == "FEES":
                    rank = (fee, *rank)
                if priority == "LIQUIDITY":
                    rank = (len(p.terms["weekdays"]) != 5, day, *rank)
                ranked.append((rank, p))
        ranked.sort(key=lambda item: item[0])
        selected = {
            p.product_id: [
                f"产品风险 {p.risk} 符合您的 C{a.grade} 测评范围",
                *(
                    [f"预算 {amount:,.2f} 元达到起购金额 {p.minimum_display}"]
                    if amount
                    else ["尚未提供预算，起购金额需进一步核对"]
                ),
                *(
                    ["尚未确认本次用款日期；每日开放也需要等待成交和到账"]
                    if not constraints.within_week
                    else ["已排除周开放产品；异步到账仍可能不满足短期用款"]
                ),
            ]
            for _, p in ranked[:3]
        }
        return WealthRecommendationResult(
            constraints=constraints,
            selected_reasons=selected,
            products=[p for _, p in ranked[:3]],
            reasons=constraints.reasons
            + ["已根据您的风险测评和本次需求筛选。产品不保证本金或收益。"]
            + ([] if ranked else ["暂无符合全部约束的产品，不放宽条件推荐"]),
            excluded=excluded,
        )

    async def frozen(self, user_id, account_id, product_id):
        return Decimal(
            await self.session.scalar(
                select(func.coalesce(func.sum(WealthHold.quantity), 0)).where(
                    WealthHold.user_id == user_id,
                    WealthHold.account_id == account_id,
                    WealthHold.product_id == product_id,
                    WealthHold.kind == "SHARES",
                    WealthHold.active.is_(True),
                )
            )
        )

    async def position(self, user_id, account_id, product_id, lock=False):
        stmt = select(WealthPosition).where(
            WealthPosition.user_id == user_id,
            WealthPosition.account_id == account_id,
            WealthPosition.product_id == product_id,
        )
        return await self.session.scalar(stmt.with_for_update() if lock else stmt)

    async def positions(self, user_id):
        results = []
        for p in (
            await self.session.scalars(
                select(WealthPosition).where(WealthPosition.user_id == user_id)
            )
        ).all():
            nav = await self.nav(p.product_id)
            v = await self.version(p.product_id)
            frozen = await self.frozen(user_id, p.account_id, p.product_id)
            pending = Decimal(0)
            for order in (
                await self.session.scalars(
                    select(WealthOrder).where(
                        WealthOrder.user_id == user_id,
                        WealthOrder.account_id == p.account_id,
                        WealthOrder.product_id == p.product_id,
                        WealthOrder.direction == "REDEEM",
                        WealthOrder.status == "CONFIRMED",
                    )
                )
            ).all():
                pending += Decimal(order.actual["net"])
            results.append(
                WealthPositionResult(
                    position_id=p.position_id,
                    product_id=p.product_id,
                    name=v.name,
                    account_id=p.account_id,
                    shares_display=f"{p.shares:.6f}",
                    frozen_display=f"{frozen:.6f}",
                    available_display=f"{p.shares - frozen:.6f}",
                    available_quantity=f"{p.shares - frozen:.6f}",
                    value_display=f"{(p.shares * nav.nav).quantize(CENT, ROUND_HALF_UP):,.2f} 元"
                    if nav
                    else None,
                    valued_at=utc(nav.published_at).isoformat() if nav else None,
                    pending_display=f"{pending:,.2f} 元",
                )
            )
        return results

    async def order_result(self, order):
        from banking_api.persistence.models import ConversationModel, OperationModel, WorkflowModel

        operation = await self.session.get(OperationModel, order.operation_id)
        workflow = await self.session.get(WorkflowModel, order.workflow_id)
        conversation = (
            await self.session.get(ConversationModel, workflow.conversation_id)
            if workflow
            else None
        )
        conversation_deleted = bool(conversation and conversation.deleted_at is not None)
        labels = {
            "CREATED": "待受理",
            "ACCEPTED": "已受理，待成交",
            "CONFIRMED": "已成交，待到账",
            "SETTLED": "最终完成",
            "REJECTED": "明确拒绝",
            "FAILED": "明确失败",
        }
        from banking_api.wealth.order_explanation import explain_order

        hold_active = await self.session.scalar(
            select(WealthHold.active).where(WealthHold.order_id == order.order_id)
        )
        return WealthOrderResult(
            **explain_order(order, operation, hold_active),
            source_task_id=workflow.source_task_id if workflow else None,
            conversation_id=workflow.conversation_id
            if workflow and not conversation_deleted
            else None,
            conversation_deleted=conversation_deleted,
            order_id=order.order_id,
            workflow_id=order.workflow_id,
            operation_id=order.operation_id,
            direction_display="申购" if order.direction == "PURCHASE" else "赎回",
            status_display=labels[order.status],
            cash_result_label="实际份额价款"
            if order.direction == "PURCHASE"
            else "实际到账金额"
            if order.status == "SETTLED"
            else "待到账金额",
            name=order.snapshot["name"],
            quantity_display=f"{order.quantity:.2f} 元"
            if order.direction == "PURCHASE"
            else f"{order.quantity:.6f} 份",
            trade_date=order.trade_date.isoformat(),
            confirm_at=utc(order.confirm_at),
            settle_at=utc(order.settle_at),
            actual=(
                order.actual
                | {
                    "nav_display": f"{Decimal(order.actual['nav']):.6f}",
                    "fee_display": f"{Decimal(order.actual['fee']):,.2f} 元",
                    "shares_display": f"{Decimal(order.actual['shares']):.6f} 份",
                    "net_display": f"{Decimal(order.actual['net']):,.2f} 元",
                    "refund_display": f"{Decimal(order.actual['refund']):,.2f} 元",
                }
            )
            if order.actual
            else None,
            sources=order.snapshot["sources"],
            unknown=operation is not None and operation.status.value == "UNKNOWN",
        )

    async def orders(self, user_id):
        return [
            await self.order_result(o)
            for o in (
                await self.session.scalars(
                    select(WealthOrder)
                    .where(WealthOrder.user_id == user_id)
                    .order_by(WealthOrder.created_at.desc())
                    .limit(100)
                )
            ).all()
        ]
