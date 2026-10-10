"""Real HTTP/current LLM smoke on a fresh isolated synthetic database.

A has no writes. B explicitly selects a mock payee, approves and commits one
synthetic transfer through the existing Workflow API. Never use a production DB.
"""

import asyncio
import json
import os

from httpx import AsyncClient
from smoke_plan_product import create_request, load_plan, wait_task

BASE_URL = os.getenv("PLAN_SMOKE_BASE_URL", "http://127.0.0.1:8001")


async def counts() -> dict:
    # Read the same isolated database used by the API, independently of its response.
    from banking_api.persistence.models import (
        ApprovalModel,
        MockBankTransferModel,
        OperationModel,
        ReauthenticationModel,
        WorkflowModel,
    )
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import create_async_engine

    url = os.environ["DATABASE_URL"]
    assert "smoke_test" in url, "Use an isolated synthetic smoke database"
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            return {
                model.__tablename__: await connection.scalar(
                    select(func.count()).select_from(model)
                )
                for model in (
                    WorkflowModel,
                    ApprovalModel,
                    ReauthenticationModel,
                    OperationModel,
                    MockBankTransferModel,
                )
            }
    finally:
        await engine.dispose()


async def main() -> None:
    assert all(value == 0 for value in (await counts()).values()), (
        "Start with a fresh database"
    )
    async with AsyncClient(base_url=BASE_URL, timeout=30, trust_env=False) as client:
        conversation, task_id = await create_request(
            client, "查一下工资卡余额，如果余额不少于999999元，给张三转500元。"
        )
        await wait_task(client, task_id, {"COMPLETED"})
        plan = await load_plan(client, conversation)
        condition = next(
            step for step in plan["steps"] if step["step_kind"] == "CONDITION"
        )
        write = next(
            step for step in plan["steps"] if step["capability"] == "TRANSFER_WORKFLOW"
        )
        assert condition["condition_decision"]["outcome"] == "FALSE"
        assert (
            write["status"] == "SKIPPED" and write["error_code"] == "CONDITION_NOT_MET"
        )
        assert write["linked_workflow_id"] is None and plan["status"] == "COMPLETED"
        no_writes = await counts()
        assert all(value == 0 for value in no_writes.values()), no_writes
        messages = (await client.get(f"/api/v1/conversations/{conversation}")).json()[
            "messages"
        ]
        answer = next(
            message["content"] for message in messages if message["role"] == "ASSISTANT"
        )
        assert "没有启动" in answer and "转账成功" not in answer
        print(
            "Smoke A: FALSE / Step SKIPPED CONDITION_NOT_MET / Plan + Task COMPLETED / "
            + json.dumps(no_writes)
            + " / Chinese no-transfer answer",
            flush=True,
        )

        conversation, task_id = await create_request(
            client, "查一下工资卡余额，如果余额不少于3000元，给张三转500元。"
        )
        await wait_task(client, task_id, {"WAITING_USER"})
        plan = await load_plan(client, conversation)
        condition = next(
            step for step in plan["steps"] if step["step_kind"] == "CONDITION"
        )
        assert condition["condition_decision"]["outcome"] == "TRUE"
        decision = condition["condition_decision"]
        write = next(
            step for step in plan["steps"] if step["capability"] == "TRANSFER_WORKFLOW"
        )
        workflow_id = write["linked_workflow_id"]
        workflow = (await client.get(f"/api/v1/workflows/{workflow_id}")).json()
        assert (await counts())["operations"] == 0
        # The mock directory has two 张三 candidates: select explicitly through the existing API.
        if workflow["status"] == "WAITING_FOR_INPUT":
            options = workflow["state"]["payee_options"]
            assert (
                options
                and workflow["state"]["required_input"]["type"] == "PAYEE_SELECTION"
            )
            selected = await client.post(
                f"/api/v1/workflows/{workflow_id}/actions/select-payee",
                json={
                    "payee_id": options[0]["payee_id"],
                    "expected_version": workflow["version"],
                },
            )
            selected.raise_for_status()
            workflow = selected.json()
        assert workflow["status"] == "READY_FOR_REVIEW", workflow["status"]
        assert workflow["risk_level"] == "YELLOW", (
            "Fresh fixture transfer must follow actual risk"
        )
        assert workflow["operation_summary"] is None
        print(
            "Smoke B: TRUE / explicit mock payee selection / READY_FOR_REVIEW / "
            "Plan + Task WAITING_USER / YELLOW / 0 Operation",
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
        workflow = (await client.get(f"/api/v1/workflows/{workflow_id}")).json()
        assert plan["status"] == "COMPLETED" and all(
            step["status"] == "COMPLETED" for step in plan["steps"]
        )
        assert (
            workflow["status"] == "SUCCEEDED"
            and workflow["operation_summary"]["status"] == "SUCCEEDED"
        )
        assert (
            next(step for step in plan["steps"] if step["step_kind"] == "CONDITION")[
                "condition_decision"
            ]
            == decision
        )
        final_counts = await counts()
        assert (
            final_counts["operations"] == 1 and final_counts["mock_bank_transfers"] == 1
        )
        print(
            "Smoke B: explicit Approval + commit / same Decision / Workflow + Operation + "
            "Step + Plan + Task SUCCEEDED/COMPLETED / " + json.dumps(final_counts),
            flush=True,
        )


if __name__ == "__main__":
    asyncio.run(main())
