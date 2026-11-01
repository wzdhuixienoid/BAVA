"""Save read-only evidence for the UI-recorded Mock transfer stages."""

import json
from pathlib import Path
import sys
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:8000/api/v1"
OPENER = build_opener(ProxyHandler({}))


def read(path):
    with OPENER.open(BASE + path, timeout=20) as response:
        return json.load(response)


def save(name, value):
    (ROOT / "evidence" / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    phase, workflow_id = sys.argv[1:3]
    ready = read("/demo/readiness")
    assert ready["provider_mode"] == "Mock" and ready["reauthentication_mode"] == "Mock"
    workflow = read("/workflows/" + workflow_id)
    save(phase, workflow)
    save(phase + "-dashboard", read("/dashboard"))
    save(phase + "-audit", read("/tasks/" + workflow["source_task_id"] + "/audit"))
    save(phase + "-task", read("/tasks/" + workflow["source_task_id"]))
    if workflow.get("operation_summary"):
        save(phase + "-operation", read("/operations/" + workflow["operation_summary"]["operation_id"]))
    print(json.dumps({"phase": phase, "workflow_id": workflow_id, "status": workflow["status"], "risk": workflow["risk_level"],
                      "approval": (workflow.get("approval_summary") or {}).get("status"),
                      "reauth": (workflow.get("reauth_summary") or {}).get("status"),
                      "operation": (workflow.get("operation_summary") or {}).get("status")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
