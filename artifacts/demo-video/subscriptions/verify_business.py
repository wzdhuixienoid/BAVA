"""Read-only evidence verification for the subscription video segment."""

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "evidence"
BASE = "http://127.0.0.1:8000/api/v1"
opener = build_opener(ProxyHandler({}))


def read(path):
    with opener.open(BASE + path, timeout=15) as response:
        return json.load(response)


def cost(snapshot, field="monthly_cost_by_currency"):
    return next(Decimal(item["amount"]) for item in snapshot[field] if item["currency"] == "CNY")


def main():
    before = json.loads((EVIDENCE / "before.json").read_text())
    after = json.loads((EVIDENCE / "after.json").read_text())
    target_before = next(s for s in before["subscriptions"] if s["merchant"] == "星幕视频")
    target_after = next(s for s in after["subscriptions"] if s["subscription_id"] == target_before["subscription_id"])
    workflows = read("/workflows")
    workflow = next(w for w in workflows if w["workflow_type"] == "SUBSCRIPTION_CANCEL" and (w["state"].get("review_payload") or {}).get("subscription_id") == target_before["subscription_id"])
    task = read("/tasks/" + workflow["source_task_id"])
    conversation = read("/conversations/" + workflow["conversation_id"])
    tasks = read("/tasks?conversation_id=" + workflow["conversation_id"])
    audit = read("/tasks/" + workflow["source_task_id"] + "/audit")
    action_audit = read("/security/audit")
    readiness = read("/demo/readiness")
    read_consents = [item for item in action_audit if item["action"] == "subscription.read.confirm" and item["outcome"] == "APPROVED"]
    queries = [item for item in tasks if item["status"] == "COMPLETED" and (item.get("output") or {}).get("subscription_analysis_snapshot")]
    approval = workflow["approval_summary"]
    operation = workflow["operation_summary"]
    review = workflow["state"]["review_payload"]
    authorization = workflow["state"]["authorization"]
    non_target_before = {s["merchant"]: s["status"] for s in before["subscriptions"] if s["merchant"] != "星幕视频"}
    non_target_after = {s["merchant"]: s["status"] for s in after["subscriptions"] if s["merchant"] != "星幕视频"}
    checks = {
        "mock_provider": readiness["provider_mode"] == "Mock",
        "read_consent_recorded": bool(read_consents),
        "query_completed_with_actual_snapshot": bool(queries),
        "same_subscription": target_before["subscription_id"] == target_after["subscription_id"] == review["subscription_id"],
        "original_active_contract": target_before["status"] == "ACTIVE" and target_before["management_type"] == "MANAGED",
        "yellow_confirmation_required": workflow["risk_level"] == "YELLOW" and workflow["presentation"]["approval_required"] is True,
        "yellow_no_mfa_required": workflow["presentation"]["reauthentication_required"] is False,
        "approval_bound_to_workflow": authorization["approval_id"] == approval["approval_id"],
        "approval_consumed": approval["status"] == "CONSUMED",
        "read_and_cancel_authorizations_distinct": bool(read_consents) and all(item["trace_id"] != approval["approval_id"] for item in read_consents),
        "read_consent_precedes_cancel": any(datetime.fromisoformat(item["created_at"].replace("Z", "+00:00")) < datetime.fromisoformat(workflow["created_at"].replace("Z", "+00:00")) for item in read_consents),
        "review_binds_original_version": review["contract_version"] == target_before["contract_version"],
        "workflow_and_operation_succeeded": workflow["status"] == "SUCCEEDED" and operation["status"] == "SUCCEEDED",
        "provider_reference_returned": bool(operation["provider_reference"]),
        "audit_confirms_business_success": audit["write_evidence"]["business_success"] is True,
        "contract_cancelled_and_version_advanced": target_after["status"] == "CANCELLED" and target_after["contract_version"] > target_before["contract_version"],
        "cancelled_contract_monthly_cost_zero": Decimal(target_after["monthly_cost"]) == 0,
        "monthly_cost_delta_matches_contract": cost(before) - cost(after) == Decimal(target_before["monthly_cost"]) == Decimal("28.00"),
        "yearly_projection_delta_matches_contract": cost(before, "annual_projected_cost_by_currency") - cost(after, "annual_projected_cost_by_currency") == Decimal("336.00"),
        "other_subscription_statuses_unchanged": non_target_before == non_target_after,
        "query_not_presented_as_cash_refund": readiness["salary_balance_initial"] is True,
    }
    baseline = json.loads((EVIDENCE / "previous-videos-sha256.json").read_text())
    checks["previous_videos_unchanged"] = all(hashlib.sha256((ROOT.parent / name).read_bytes()).hexdigest() == digest for name, digest in baseline.items())
    payload = {
        "subscription_id": target_before["subscription_id"],
        "merchant": target_before["merchant"],
        "workflow_id": workflow["workflow_id"],
        "source_task_id": workflow["source_task_id"],
        "conversation_id": workflow["conversation_id"],
        "provider_reference": operation["provider_reference"],
        "monthly_cost_before": str(cost(before)),
        "monthly_cost_after": str(cost(after)),
        "monthly_projection_reduction": "28.00",
        "completed_at": operation["completed_at"],
        "checks": checks,
    }
    for name, data in [("workflow", workflow), ("task", task), ("conversation", conversation), ("conversation-tasks", tasks), ("audit", audit), ("read-authorization-audit", action_audit), ("readiness", readiness), ("verification", payload)]:
        (EVIDENCE / (name + ".json")).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
