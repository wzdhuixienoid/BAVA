"""Real HTTP/current LLM smoke for constrained read DAG and subscription handoff.

Start the current API against an isolated synthetic database, then run this script.
No credential or hidden reasoning is printed. This smoke explicitly approves and
commits one synthetic subscription cancellation; it never authorizes a transfer.
"""

import asyncio
import os
import time

from httpx import AsyncClient

BASE_URL = os.getenv("PLAN_SMOKE_BASE_URL", "http://127.0.0.1:8001")


async def wait_task(client: AsyncClient, task_id: str, statuses: set[str]) -> dict:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        response = await client.get(f"/api/v1/tasks/{task_id}")
        response.raise_for_status()
        task = response.json()
        if task["status"] in statuses:
            return task
        if task["status"] in {"FAILED", "CANCELLED"}:
            raise AssertionError({"status": task["status"], "error": task.get("error")})
        await asyncio.sleep(0.25)
    raise TimeoutError("Plan smoke timed out")


async def create_request(client: AsyncClient, query: str) -> tuple[str, str]:
    response = await client.post(
        "/api/v1/conversations", json={"title": "计划产品 Smoke"}
    )
    response.raise_for_status()
    conversation_id = response.json()["conversation_id"]
    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages", json={"content": query}
    )
    response.raise_for_status()
    return conversation_id, response.json()["task_id"]


async def load_plan(client: AsyncClient, conversation_id: str) -> dict:
    response = await client.get(
        "/api/v1/plans", params={"conversation_id": conversation_id}
    )
    response.raise_for_status()
    plans = response.json()
    assert len(plans) == 1
    return plans[0]


async def main() -> None:
    async with AsyncClient(base_url=BASE_URL, timeout=30, trust_env=False) as client:
        conversation, task_id = await create_request(
            client, "先查一下工资卡余额，再分析一下2026年9月的消费。"
        )
        task = await wait_task(client, task_id, {"COMPLETED"})
        assert task["executor_id"] == "planner:constrained"
        plan = await load_plan(client, conversation)
        assert plan["status"] == "COMPLETED"
        assert {step["capability"] for step in plan["steps"]} == {
            "ACCOUNT_QUERY",
            "FINANCIAL_ANALYSIS",
        }
        assert all(step["status"] == "COMPLETED" for step in plan["steps"])
        print(
            "Smoke A: COMPLEX_PLAN / 2 bounded read outputs / Plan + Task COMPLETED",
            flush=True,
        )

        consent = await client.post(
            "/api/v1/security/subscription-read-consent", json={"confirmed": True}
        )
        consent.raise_for_status()
        conversation, task_id = await create_request(
            client, "先看看我有哪些订阅，然后取消星幕视频。"
        )
        await wait_task(client, task_id, {"WAITING_USER"})
        plan = await load_plan(client, conversation)
        assert plan["status"] == "WAITING_USER"
        write = next(
            step
            for step in plan["steps"]
            if step["capability"] == "SUBSCRIPTION_CANCEL_WORKFLOW"
        )
        assert write["status"] == "WAITING_USER"
        workflow_id = write["linked_workflow_id"]
        response = await client.get(f"/api/v1/workflows/{workflow_id}")
        response.raise_for_status()
        workflow = response.json()
        assert workflow["status"] == "READY_FOR_REVIEW"
        assert workflow["risk_level"] == "YELLOW"
        assert workflow["operation_summary"] is None
        assert workflow["reauth_summary"] is None
        print(
            "Smoke B: analysis COMPLETED / WAITING_USER / YELLOW / 0 Operation / no reauth",
            flush=True,
        )
        for action in ("approve", "commit"):
            response = await client.post(
                f"/api/v1/workflows/{workflow_id}/actions/{action}",
                json={"expected_version": workflow["version"]},
            )
            response.raise_for_status()
            workflow = response.json()
        await wait_task(client, task_id, {"COMPLETED"})
        plan = await load_plan(client, conversation)
        assert plan["status"] == "COMPLETED"
        response = await client.get(f"/api/v1/workflows/{workflow_id}")
        response.raise_for_status()
        workflow = response.json()
        assert workflow["status"] == "SUCCEEDED"
        assert workflow["operation_summary"]["status"] == "SUCCEEDED"
        assert workflow["reauth_summary"] is None
        operation_id = workflow["operation_summary"]["operation_id"]
        retry = await client.post(
            f"/api/v1/workflows/{workflow_id}/actions/commit",
            json={"expected_version": workflow["version"]},
        )
        retry.raise_for_status()
        assert retry.json()["operation_summary"]["operation_id"] == operation_id
        print(
            "Smoke B: same Operation SUCCEEDED / Workflow + Step + Plan + Task COMPLETED",
            flush=True,
        )


if __name__ == "__main__":
    asyncio.run(main())
