"""One grounded assistant answer for deterministic anomaly evidence."""

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel

from banking_api.agent_skills import packaged_catalog
from banking_api.financial.anomaly_models import TransactionAnomalySnapshot
from banking_api.financial.presentation import CHINA_TIME
from banking_api.financial.presentation import transaction_time as date_text
from banking_api.financial.review_models import SpendingReview, SpendingReviewItem
from banking_api.skills.models import SkillDefinition

LABELS = {
    "AMOUNT_SPIKE": "金额明显高于历史",
    "RAPID_DUPLICATE": "短时重复扣款",
    "NEW_MERCHANT_HIGH_AMOUNT": "新商户高额消费",
    "SUBSCRIPTION_PRICE_SPIKE": "订阅涨价",
}


class AnomalyAnalysisAnswer(BaseModel):
    answer: str


def number(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def cell(value: str) -> str:
    for token in ("\\", "|", "*", "_", "[", "]", "<", ">", "`"):
        value = value.replace(token, "\\" + token)
    return value.replace("\n", " ").replace("\r", " ")


class TransactionAnomalyAnalysisSkill:
    def __init__(self):
        self.active_skill = packaged_catalog().bind_business_skill(self.definition)

    def review(self, snapshot: TransactionAnomalySnapshot) -> SpendingReview:
        priority = {
            "RAPID_DUPLICATE": 0,
            "SUBSCRIPTION_PRICE_SPIKE": 1,
            "NEW_MERCHANT_HIGH_AMOUNT": 2,
            "AMOUNT_SPIKE": 3,
        }
        ordered = sorted(
            snapshot.anomalies,
            key=lambda item: (
                min(priority[rule.value] for rule in item.anomaly_types),
                -item.occurred_at.timestamp(),
            ),
        )
        items = [
            SpendingReviewItem(
                transaction_id=item.transaction_id,
                occurred_at=item.occurred_at,
                merchant=item.merchant_display,
                amount_display=number(item.amount),
                reason="、".join(LABELS[rule.value] for rule in item.anomaly_types),
            )
            for item in ordered[:3]
        ]
        count = snapshot.total_anomaly_count or len(snapshot.anomalies)
        message = (
            f"发现 {count} 笔值得核对的交易。"
            if count
            else "本次检查未发现明显异常，不代表已排除所有风险。"
        )
        notes = []
        status = "REVIEWED"
        if snapshot.analyzed_transaction_count == 0:
            status, message = "UNAVAILABLE", "所选区间没有可分析的消费记录，无法进行异常检查。"
        if snapshot.baseline_skipped_count:
            notes.append("部分消费缺少足够的同商户或同分类历史，未作金额偏离判断。")
            status = "PARTIAL"
        if snapshot.available_data_started_at and (
            snapshot.analysis_period_started_at.astimezone(CHINA_TIME).date()
            < snapshot.available_data_started_at.astimezone(CHINA_TIME).date()
        ):
            notes.append("所选区间早于首条可用记录，更早部分无法检查。")
            status = "PARTIAL"
        if snapshot.available_data_ended_at and (
            (snapshot.analysis_period_ended_at - timedelta(microseconds=1))
            .astimezone(CHINA_TIME)
            .date()
            > snapshot.available_data_ended_at.astimezone(CHINA_TIME).date()
        ):
            notes.append("所选区间晚于末条可用记录，更晚部分无法检查。")
            status = "PARTIAL"
        if snapshot.analyzed_transaction_count == 0:
            status = "UNAVAILABLE"
        if count > len(items):
            notes.insert(0, f"仅列出优先核对的 {len(items)} 笔，其余可查看完整明细。")
        lines = ["### 值得核对的交易", message]
        lines += [
            f"- {date_text(item.occurred_at)}，{cell(item.merchant)}，"
            f"{item.amount_display} 元：{item.reason}。"
            for item in items
        ]
        if items:
            lines.append("这些提示不代表已确认欺诈；可继续询问该区间的异常交易明细。")
        lines.extend(notes)
        return SpendingReview(
            status=status,
            message=message,
            notes=notes,
            items=items,
            total_count=count,
            answer="\n\n".join(lines),
        )

    definition = SkillDefinition(
        skill_id="skill:transaction-anomaly-analysis",
        agent_skill_name="transaction-anomaly-analysis",
        version=1,
        description="根据异常检测快照组织统一的中文说明、交易表格及核对建议。",
        input_schema=TransactionAnomalySnapshot,
        output_schema=AnomalyAnalysisAnswer,
        allowed_tools=(),
    )

    def execute(self, snapshot: TransactionAnomalySnapshot) -> AnomalyAnalysisAnswer:
        lines = [
            "## 异常交易分析",
            f"分析区间（北京时间）：{date_text(snapshot.analysis_period_started_at)} 至 "
            f"{date_text(snapshot.analysis_period_ended_at)}。",
            "异常提示表示交易与历史模式不同，不代表已确认欺诈。请结合实际消费核对。",
        ]
        if snapshot.available_data_started_at and snapshot.available_data_ended_at:
            lines.append(
                f"可用交易记录：{date_text(snapshot.available_data_started_at)} 至 "
                f"{date_text(snapshot.available_data_ended_at)}。"
            )
            if (
                snapshot.analysis_period_started_at.astimezone(CHINA_TIME).date()
                < snapshot.available_data_started_at.astimezone(CHINA_TIME).date()
            ):
                lines.append(
                    "所选区间早于首条可用记录；更早部分没有交易证据，无法进行异常分析。以下仅展示已有证据支持的结果。"
                )
            if (snapshot.analysis_period_ended_at - timedelta(microseconds=1)).astimezone(
                CHINA_TIME
            ).date() > snapshot.available_data_ended_at.astimezone(CHINA_TIME).date():
                lines.append("所选区间的结束日期超出可用记录范围，缺少记录的后续部分无法分析。")
        if snapshot.analyzed_transaction_count == 0 and not snapshot.anomalies:
            lines.append("该区间没有可分析的已入账消费记录。")
        elif not snapshot.anomalies:
            lines.append("在本次分析使用的确定性规则下没有发现明显异常；未检出不等于不存在欺诈。")
        else:
            count = snapshot.total_anomaly_count or len(snapshot.anomalies)
            lines.append(f"发现 {count} 笔值得关注的交易。")
            if snapshot.truncated:
                lines.append(f"以下展示最近 {len(snapshot.anomalies)} 笔；其余结果未在本表展示。")
            lines.extend(
                [
                    "",
                    "| 日期 | 商户 | 金额（元） | 异常类型 | 严重度 | 金额倍数（对历史中位数） |",
                    "| --- | --- | ---: | --- | --- | ---: |",
                ]
            )
            for item in snapshot.anomalies:
                ratio = next((e.ratio for e in item.evidence.values() if e.ratio is not None), None)
                labels = "、".join(
                    LABELS.get(rule.value, "值得关注") for rule in item.anomaly_types
                )
                lines.append(
                    f"| {date_text(item.occurred_at)} | {cell(item.merchant_display)} "
                    f"| {number(item.amount)} "
                    f"| {labels} | {'高' if item.severity == 'HIGH' else '中'} "
                    f"| {number(ratio) if ratio is not None else '—'} |"
                )
            lines.extend(["", "### 核对建议"])
            present = {rule.value for item in snapshot.anomalies for rule in item.anomaly_types}
            advice = {
                "AMOUNT_SPIKE": "核对金额明显高于历史的消费是否与你的实际购买相符。",
                "NEW_MERCHANT_HIGH_AMOUNT": "核对首次出现的大额商户及交易用途。",
                "RAPID_DUPLICATE": "核对同一商户的短时重复扣款是否为多次购买或重复收费。",
                "SUBSCRIPTION_PRICE_SPIKE": "查看订阅账单，确认价格或套餐是否发生变化。",
            }
            lines.extend(f"- {advice[rule]}" for rule in advice if rule in present)
        if snapshot.baseline_skipped_count:
            lines.append(
                f"其中 {snapshot.baseline_skipped_count} 笔消费因历史样本不足未执行金额偏离规则；"
                "重复扣款和订阅涨价规则仍按各自证据执行。"
            )
        elif snapshot.insufficient_baseline:
            lines.append("历史样本不足，部分金额规则无法执行，不能据此排除异常。")
        return AnomalyAnalysisAnswer(answer="\n\n".join(lines[:3]) + "\n" + "\n".join(lines[3:]))
