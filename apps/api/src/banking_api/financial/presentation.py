from datetime import datetime, timedelta, timezone

CHINA_TIME = timezone(timedelta(hours=8))


def transaction_time(value: datetime) -> str:
    return value.astimezone(CHINA_TIME).strftime("%Y年%m月%d日 %H:%M")


CATEGORY_LABELS = {
    "FOOD": "餐饮",
    "SHOPPING": "购物",
    "TRAVEL": "旅行",
    "HOUSING": "住房",
    "TRANSPORT": "通勤",
    "TRANSPORTATION": "通勤",
    "UTILITIES": "水电通信",
    "SUBSCRIPTION": "订阅",
    "HEALTH": "健康",
    "ENTERTAINMENT": "娱乐",
    "OTHER": "其他",
    "TRANSFER": "转账",
    "SALARY": "工资",
}


def category_label(value: str) -> str:
    return CATEGORY_LABELS.get(
        value, value if any("\u4e00" <= c <= "\u9fff" for c in value) else "其他"
    )


def with_account_names(task, accounts):  # type: ignore[no-untyped-def]
    """Attach owner-scoped display metadata to saved analysis without changing stored facts."""
    output = task.output
    if not output or not output.get("analysis_snapshot"):
        return task
    snapshot = output["analysis_snapshot"]
    transactions = (snapshot.get("top_transactions") or {}).get("transactions", [])
    referenced = {item["account_id"] for item in transactions}
    names = {
        item["account_id"]: item["display_name"]
        for item in accounts
        if item["account_id"] in referenced
    }
    return task.model_copy(update={"output": {**output, "financial_account_names": names}})


def with_anomaly_answer(task):  # type: ignore[no-untyped-def]
    """Re-present saved snapshots through the same Skill without rerunning detection."""
    from pydantic import ValidationError

    from banking_api.financial.anomaly_models import TransactionAnomalySnapshot
    from banking_api.skills.transaction_anomaly_analysis import TransactionAnomalyAnalysisSkill

    snapshot = (task.output or {}).get("transaction_anomaly_snapshot")
    if not snapshot or (task.output or {}).get("anomaly_presentation") == "combined":
        return task
    try:
        validated = TransactionAnomalySnapshot.model_validate(snapshot)
    except ValidationError:
        return task
    answer = TransactionAnomalyAnalysisSkill().execute(validated).answer
    return task.model_copy(update={"output": {**task.output, "transaction_anomaly_answer": answer}})
