"""Verify recorded Mock transfer stages against saved authoritative responses."""

from decimal import Decimal
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
E = ROOT / "evidence"


def load(name):
    return json.loads((E / (name + ".json")).read_text())


def salary(snapshot):
    return Decimal(next(a["balance"] for a in snapshot["accounts"] if a["account_id"] == "acc_salary"))


def main():
    before, after = load("dashboard-before"), load("dashboard-after")
    yr, ya, ys = [load("yellow-" + phase) for phase in ["review", "approved", "success"]]
    rr, rc, rh, rv, rs = [load("red-" + phase) for phase in ["review", "confirmed", "challenge", "verified", "success"]]
    transactions = load("transactions-after")["transactions"]
    checks = {
        "mock_bank_and_mock_auth": load("readiness-before")["provider_mode"] == load("readiness-after")["provider_mode"] == "Mock" and load("readiness-before")["reauthentication_mode"] == load("readiness-after")["reauthentication_mode"] == "Mock",
        "demo_owner_and_zero_initial_exposure": load("readiness-before")["owner_is_demo_user"] and load("readiness-before")["daily_exposure_zero"],
        "same_name_candidates_require_ui_choice": {p["masked_account"] for p in yr["state"]["payee_options"]} == {"****2231", "****9102"} and "选择张三，星河银行（虚构），****2231" in (ROOT / "source/03-yellow-payee-bottom.txt").read_text() and "选择张三，蓝海银行（虚构），****9102" in (ROOT / "source/03-yellow-payee-bottom.txt").read_text(),
        "selected_payee_bound_to_review": all(w["state"]["review_payload"]["payee_id"] == "payee_001" and w["state"]["review_payload"]["payee_masked_account"] == "****2231" for w in [yr, ya, ys]),
        "yellow_risk_requires_confirmation_without_mfa": all(w["risk_level"] == "YELLOW" and w["risk_decision"]["required_approval"] and not w["risk_decision"]["required_reauthentication"] for w in [yr, ya, ys]),
        "yellow_amount_within_actual_limits": Decimal(yr["risk_decision"]["requested_amount"]) == Decimal("100") < Decimal(yr["risk_decision"]["passwordless_limit"]) == Decimal("200") and Decimal(yr["risk_decision"]["projected_daily_total"]) == Decimal("100") <= Decimal(yr["risk_decision"]["threshold"]),
        "yellow_confirmed_is_not_submitted": ya["status"] == "READY_FOR_COMMIT" and ya["approval_summary"]["status"] == "APPROVED" and ya["operation_summary"] is None and salary(load("yellow-approved-dashboard")) == salary(before),
        "yellow_final_success_and_consumed_approval": ys["status"] == ys["operation_summary"]["status"] == "SUCCEEDED" and ys["approval_summary"]["status"] == "CONSUMED" and ys["reauth_summary"] is None,
        "yellow_debit_matches_100": salary(before) - salary(load("yellow-success-dashboard")) == Decimal("100"),
        "red_bound_to_requested_payee_and_remark": all(w["state"]["review_payload"]["payee_id"] == "payee_003" and Decimal(w["state"]["review_payload"]["amount"]) == Decimal("1200") and w["state"]["review_payload"]["remark"] == "房租" for w in [rr, rc, rh, rv, rs]),
        "red_risk_requires_confirmation_and_mfa": all(w["risk_level"] == "RED" and w["risk_decision"]["required_approval"] and w["risk_decision"]["required_reauthentication"] for w in [rr, rc, rh, rv, rs]),
        "red_cumulative_exposure_1300": Decimal(rr["risk_decision"]["daily_successful_total"]) == Decimal("100") and Decimal(rr["risk_decision"]["requested_amount"]) == Decimal("1200") and Decimal(rr["risk_decision"]["projected_daily_total"]) == Decimal("1300"),
        "red_exceeds_daily_threshold_and_single_limit": set(rr["risk_decision"]["reason_codes"]) == {"DAILY_TRANSFER_LIMIT_EXCEEDED", "PASSWORDLESS_LIMIT_REACHED"},
        "red_confirmation_stops_for_auth": rc["status"] == "REAUTH_REQUIRED" and rc["approval_summary"]["status"] == "APPROVED" and rc["operation_summary"] is None,
        "mock_challenge_pending_before_verification": rh["status"] == "REAUTH_REQUIRED" and rh["reauth_summary"]["status"] == "PENDING" and rh["reauth_summary"]["method"] == "MOCK_CODE" and rh["operation_summary"] is None,
        "verified_is_not_submitted": rv["status"] == "READY_FOR_COMMIT" and rv["reauth_summary"]["status"] == "VERIFIED" and rv["operation_summary"] is None,
        "no_red_debit_before_commit": all(salary(load("red-" + phase + "-dashboard")) == salary(load("yellow-success-dashboard")) for phase in ["review", "confirmed", "challenge", "verified"]),
        "red_auth_bound_to_same_approval_and_payload": len({w["state"]["authorization"]["approval_id"] for w in [rc, rh, rv, rs]}) == 1 and len({w["state"]["authorization"]["approval_payload_hash"] for w in [rc, rh, rv, rs]}) == 1 and rv["state"]["authorization"]["reauth_id"] == rv["reauth_summary"]["reauth_id"] == rh["reauth_summary"]["reauth_id"],
        "red_final_success_and_consumed_approval": rs["status"] == rs["operation_summary"]["status"] == "SUCCEEDED" and rs["approval_summary"]["status"] == "CONSUMED" and rs["reauth_summary"]["status"] == "VERIFIED",
        "red_debit_matches_1200": salary(load("yellow-success-dashboard")) - salary(after) == Decimal("1200"),
        "total_debit_matches_1300": salary(before) - salary(after) == Decimal("1300") and salary(after) == Decimal("22564.52"),
        "other_account_balances_unchanged": {a["account_id"]: a["balance"] for a in before["accounts"] if a["account_id"] != "acc_salary"} == {a["account_id"]: a["balance"] for a in after["accounts"] if a["account_id"] != "acc_salary"},
        "security_guard_remains_normal": load("security-before")["status"] == load("security-after")["status"] == "NORMAL",
    }
    facts = []
    for color, workflow in [("yellow", ys), ("red", rs)]:
        op = load(color + "-success-operation")
        audit = load(color + "-success-audit")
        write = audit["write_evidence"]
        reference = op["provider_reference"]
        rows = [row for row in transactions if row["transaction_id"] == "transfer:" + reference + ":debit"]
        review = workflow["state"]["review_payload"]
        checks[color + "_single_ledger_entry_matches_receipt"] = len(rows) == 1 and Decimal(rows[0]["amount"]) == Decimal(review["amount"]) and rows[0]["direction"] == "DEBIT" and rows[0]["counterparty_id"] == review["payee_id"] and rows[0]["description"] == review["remark"] and rows[0]["account_id"] == review["source_account_id"]
        checks[color + "_operation_matches_workflow"] = op["workflow_id"] == workflow["workflow_id"] and op["operation_id"] == workflow["operation_summary"]["operation_id"] and op["status"] == "SUCCEEDED"
        checks[color + "_audit_confirms_one_submission_and_success"] = write["business_success"] is True and write["operation_count"] == write["provider_ledger_count"] == write["provider_submission_count"] == 1
        facts.append({"risk": color.upper(), "workflow_id": workflow["workflow_id"], "operation_id": op["operation_id"], "amount": review["amount"], "payee": review["payee_display_name"], "masked_account": review["payee_masked_account"], "remark": review["remark"], "completed_at": op["completed_at"]})
    before_ids = {w["workflow_id"] for w in load("workflows-before")}
    new_transfers = {w["workflow_id"] for w in load("workflows-after") if w["workflow_type"] == "TRANSFER" and w["workflow_id"] not in before_ids}
    checks["exactly_two_new_transfer_workflows"] = new_transfers == {ys["workflow_id"], rs["workflow_id"]}
    baseline = load("previous-videos-sha256")
    checks["previous_videos_unchanged"] = all(hashlib.sha256((ROOT.parent / name).read_bytes()).hexdigest() == digest for name, digest in baseline.items())
    checks["no_verification_code_in_ui_capture_text"] = all("246810" not in p.read_text() for p in (ROOT / "source").glob("*.txt"))
    result = {"salary_balance_before": str(salary(before)), "salary_balance_after_yellow": str(salary(load("yellow-success-dashboard"))), "salary_balance_after_both": str(salary(after)), "total_debit": "1300.00", "reauthentication_mode": "MOCK_CODE", "transfers": facts, "checks": checks}
    (E / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    assert all(checks.values()), [key for key, ok in checks.items() if not ok]


if __name__ == "__main__":
    main()
