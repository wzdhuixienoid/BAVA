from uuid import UUID

from sqlalchemy import select

from banking_api.application.conversation_service import ConversationService
from banking_api.application.task_service import TaskService
from banking_api.domain.enums import TaskStatus
from banking_api.llm.models import LLMResponse, LLMToolCall
from banking_api.persistence.models import EventModel


async def test_fake_agent_runtime_e2e_persists_multistep_result(app) -> None:
    factory = app.state.test_session_factory
    bus = app.state.event_bus
    async with factory() as session:
        conversation = await ConversationService(session, bus).create(
            user_id="dev-user-001", title="Agent E2E"
        )
    async with factory() as session:
        accepted = await ConversationService(session, bus).accept_message(
            conversation_id=conversation.conversation_id,
            user_id="dev-user-001",
            content="我的工资卡余额是多少？",
        )

    runner = app.state.test_make_runner(
        [
            LLMResponse(tool_calls=[LLMToolCall(id="call_1", name="list_accounts", arguments={})]),
            LLMResponse(
                tool_calls=[
                    LLMToolCall(
                        id="call_2",
                        name="get_balance",
                        arguments={"account_id": "acc_salary"},
                    )
                ]
            ),
            LLMResponse(content="工资卡余额为 23,864.52 元。"),
        ]
    )
    await runner.run(accepted.task_id)

    async with factory() as session:
        task = await TaskService(session).get(UUID(str(accepted.task_id)), user_id="dev-user-001")
        loaded = await ConversationService(session, bus).get(
            conversation_id=conversation.conversation_id,
            user_id="dev-user-001",
        )
        event_rows = list(
            (
                await session.execute(
                    select(EventModel)
                    .where(EventModel.task_id == accepted.task_id)
                    .order_by(EventModel.sequence)
                )
            ).scalars()
        )

    assert task.status is TaskStatus.COMPLETED
    assert {key: value for key, value in task.output.items() if key != "account_results"} == {
        "agent_id": "agent:personal-banking",
        "assistant_message_id": str(loaded.messages[-1].message_id),
        "steps": 3,
        "tool_calls": 2,
        "requested_output": "ANSWER",
    }
    results = task.model_dump(mode="json")["output"]["account_results"]
    assert [result["kind"] for result in results] == ["ACCOUNT_LIST", "ACCOUNT_BALANCE"]
    assert results[1]["balance"] == "23864.52"
    assert results[1]["balance_display"] == "¥23,864.52"
    assert task.version == 8
    assert task.executor_id == "agent:personal-banking"
    assert loaded.messages[-1].content == "工资卡当前余额：¥23,864.52"
    assert [event.event_type for event in event_rows].count("tool.call.completed") == 2
    assert all("23864.52" not in str(event.data_json) for event in event_rows)
