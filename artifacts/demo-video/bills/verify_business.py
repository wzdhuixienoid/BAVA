"""Read-only local API verification for the report shown in this video segment."""

import json
import sys
from decimal import Decimal
from pathlib import Path
from urllib.request import ProxyHandler, build_opener
from uuid import UUID

ROOT = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:8000/api/v1"
opener = build_opener(ProxyHandler({}))


def read(path):
    with opener.open(BASE + path, timeout=15) as response:
        return json.load(response)


def main():
    report_id = str(UUID(sys.argv[1]))
    report = read("/reports/" + report_id)
    task = read("/tasks/" + report["source_task_id"])
    conversation = read("/conversations/" + report["conversation_id"])
    audit = read("/tasks/" + report["source_task_id"] + "/audit")
    history = read("/reports")
    body = report["content"]
    categories = body["category_breakdown"]
    total = Decimal(body["overview"]["total_spending"])
    comparison = body["period_comparison"]
    rent = next(item for item in categories if item["category"] == "HOUSING")
    rent_transactions = [item for item in body["top_transactions"] if item["category"] == "HOUSING"]
    checks = {
        "period_matches_request": report["period"] == "2026-08",
        "task_completed": task["status"] == "COMPLETED",
        "same_report_and_task": task["output"]["report_id"] == report_id,
        "same_conversation": report["conversation_id"] == task["conversation_id"],
        "request_matches_capture": any(item["message_id"] == task["input"]["message_id"] and item["content"] == "分析2026年8月消费，生成报告" for item in conversation["messages"]),
        "category_amounts_sum_to_total": sum(Decimal(item["amount"]) for item in categories) == total,
        "category_counts_sum_to_total": sum(item["transaction_count"] for item in categories) == body["overview"]["transaction_count"],
        "period_change_matches_total": total - Decimal(comparison["previous_spending"]) == Decimal(comparison["absolute_change"]),
        "rent_summary_matches_transaction": sum(Decimal(item["amount"]) for item in rent_transactions) == Decimal(rent["amount"]),
        "report_saved_in_history": any(item["report_id"] == report_id for item in history),
        "no_financial_write_started": audit["write_evidence"]["no_write_started"],
        "no_workflow_or_operation": audit["write_evidence"]["workflow_count"] == 0 and audit["write_evidence"]["operation_count"] == 0,
    }
    out = ROOT / "evidence"
    out.mkdir(exist_ok=True)
    for name, value in [("report", report), ("task", task), ("audit", audit), ("conversation", conversation)]:
        (out / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    result = {
        "report_id": report_id,
        "task_id": report["source_task_id"],
        "conversation_id": report["conversation_id"],
        "period": report["period"],
        "total_spending": str(total),
        "transaction_count": body["overview"]["transaction_count"],
        "rent_amount": rent["amount"],
        "created_at": report["created_at"],
        "checks": checks,
    }
    (out / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
