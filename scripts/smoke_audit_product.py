"""Real HTTP transfer authorization, Operation and bounded audit evidence smoke.

Only localhost synthetic development/test products; explicitly approves one YELLOW
transfer. No credential or model response is printed.
"""

import asyncio
import os

from demo_preflight import local_url
from httpx import AsyncClient
from smoke_plan_product import create_request, wait_task

BASE_URL = local_url(os.getenv("AUDIT_SMOKE_BASE_URL", "http://127.0.0.1:8001"))


async def reviewed(client, task_id):
    task = await wait_task(client, task_id, {"COMPLETED"})
    workflow_id = task["output"]["workflow_id"]
    response = await client.get(f"/api/v1/workflows/{workflow_id}")
    response.raise_for_status()
    workflow = response.json()
    assert workflow["status"] == "READY_FOR_REVIEW"
    return workflow


async def main():
    async with AsyncClient(base_url=BASE_URL, timeout=30, trust_env=False) as client:
        readiness = await client.get("/api/v1/demo/readiness")
        readiness.raise_for_status()
        assert readiness.json()["provider_mode"] == "Mock"
        _, task_id = await create_request(client, "从工资卡给李小雨转500元")
        workflow = await reviewed(client, task_id)
        assert workflow["risk_decision"]["level"] == "YELLOW"
        path = f"/api/v1/workflows/{workflow['workflow_id']}/actions"
        response = await client.post(
            f"{path}/approve", json={"expected_version": workflow["version"]}
        )
        response.raise_for_status()
        workflow = response.json()
        response = await client.post(
            f"{path}/commit", json={"expected_version": workflow["version"]}
        )
        response.raise_for_status()
        operation = response.json()
        assert operation["status"] == "SUCCEEDED"
        response = await client.get(f"/api/v1/tasks/{task_id}/audit")
        response.raise_for_status()
        audit = response.json()
        types = {e["event_type"] for e in audit["entries"]}
        assert {
            "conversation.message.created",
            "workflow.risk_evaluated",
            "approval.approved",
            "approval.consumed",
            "operation.created",
            "provider.submit_started",
            "operation.succeeded",
        } <= types
        assert audit["write_evidence"]["business_success"] is True
        assert audit["write_evidence"]["provider_ledger_count"] == 1
        for forbidden in (
            "verification_code",
            "mock_reauth_code",
            "Authorization",
            "Bearer ",
            "llm_api_key",
            "scratchpad",
            "chain_of_thought",
        ):
            assert forbidden not in response.text
        print(
            "PASS HTTP audit: Approval → Operation → Provider SUCCEEDED; no secret fields"
        )


if __name__ == "__main__":
    asyncio.run(main())
