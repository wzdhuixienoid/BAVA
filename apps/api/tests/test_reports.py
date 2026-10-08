import json
import re
from pathlib import Path

from banking_api.application.conversation_service import ConversationService
from banking_api.application.report_service import (
    ReportNotFoundError,
    ReportService,
    source_snapshot_hash,
)
from banking_api.domain.enums import RuntimeBackend
from banking_api.financial.analysis_snapshot import (
    FinancialAnalysisSnapshot,
    ToolEvidence,
)
from banking_api.financial.models import (
    CategoryBreakdown,
    SpendingPeriodComparison,
    SpendingSummary,
    TopTransactions,
)
from banking_api.llm.fake_provider import FakeLLMProvider
from banking_api.llm.models import LLMResponse
from banking_api.skill_runtime.executor import SkillExecutor
from banking_api.skills.monthly_spending_report import MonthlySpendingReportSkill

DATA_DIR = Path(__file__).parents[1] / "src/banking_api/mock_bank/data"


def golden_snapshot() -> FinancialAnalysisSnapshot:
    golden = json.loads((DATA_DIR / "golden_financial_metrics.json").read_text(encoding="utf-8"))
    august = golden["months"]["2026-08"]
    return FinancialAnalysisSnapshot(
        period="2026-08",
        account_ids=[],
        spending_summary=SpendingSummary.model_validate(august["summary"]),
        category_breakdown=CategoryBreakdown.model_validate(august["category_breakdown"]),
        period_comparison=SpendingPeriodComparison.model_validate(
            golden["comparisons"]["2026-07_to_2026-08"]
        ),
        top_transactions=TopTransactions.model_validate(august["top_transactions"]),
        tool_evidence=[
            ToolEvidence(
                capability_id="transaction.spending_summary",
                input={"month": "2026-08"},
            ),
            ToolEvidence(
                capability_id="transaction.category_breakdown",
                input={"month": "2026-08"},
            ),
            ToolEvidence(
                capability_id="transaction.compare_periods",
                input={"month": "2026-08"},
            ),
            ToolEvidence(
                capability_id="transaction.top_transactions",
                input={"month": "2026-08", "limit": 5},
            ),
        ],
    )


def narrative_response() -> LLMResponse:
    return LLMResponse(
        content=json.dumps(
            {
                "headline": "本月支出上升且结构集中",
                "insights": [
                    {
                        "type": "STRUCTURE",
                        "title": "住房是最主要的支出类别",
                        "narrative": "消费结构主要由住房、购物和旅行构成。",
                        "evidence_refs": ["category_breakdown.HOUSING.share"],
                    },
                    {
                        "type": "CHANGE",
                        "title": "旅行和购物是主要增量来源",
                        "narrative": "本月支出明显上升，旅行和购物的变化最突出。",
                        "evidence_refs": [
                            "category_breakdown.TRAVEL.absolute_change",
                            "category_breakdown.SHOPPING.absolute_change",
                        ],
                    },
                ],
            },
            ensure_ascii=False,
        )
    )


async def create_source(app, *, user_id: str = "dev-user-001"):  # type: ignore[no-untyped-def]
    factory = app.state.test_session_factory
    async with factory() as session:
        service = ConversationService(
            session,
            app.state.event_bus,
            runtime_backend=RuntimeBackend.LANGGRAPH,
        )
        conversation = await service.create(user_id=user_id, title="Report test")
        accepted = await service.accept_message(
            conversation_id=conversation.conversation_id,
            user_id=user_id,
            content="生成一份2026年8月消费报告",
        )
    return conversation, accepted


async def persist_golden_report(app, *, user_id: str = "dev-user-001"):  # type: ignore[no-untyped-def]
    conversation, accepted = await create_source(app, user_id=user_id)
    snapshot = golden_snapshot()
    report = await SkillExecutor(FakeLLMProvider([narrative_response()])).execute(snapshot)
    async with app.state.test_session_factory() as session:
        artifact = await ReportService(session).create_report(
            user_id=user_id,
            conversation_id=conversation.conversation_id,
            source_task_id=accepted.task_id,
            report=report,
            snapshot=snapshot,
            skill=MonthlySpendingReportSkill.definition,
        )
        await session.commit()
    return artifact, conversation, accepted


async def test_report_create_read_list_provenance_and_idempotency(app) -> None:
    artifact, conversation, accepted = await persist_golden_report(app)

    async with app.state.test_session_factory() as session:
        service = ReportService(session)
        existing = await service.create_report(
            user_id="dev-user-001",
            conversation_id=conversation.conversation_id,
            source_task_id=accepted.task_id,
            report=artifact.content,
            snapshot=golden_snapshot(),
            skill=MonthlySpendingReportSkill.definition,
        )
        detail = await service.get_report_for_user(
            artifact.report_id,
            user_id="dev-user-001",
        )
        reports = await service.list_reports_for_user(
            user_id="dev-user-001",
            conversation_id=conversation.conversation_id,
        )

    assert existing.report_id == artifact.report_id
    assert detail.source_task_id == accepted.task_id
    assert detail.skill_id == "skill:monthly-spending-report"
    assert detail.skill_version == 1
    assert detail.source_snapshot_hash == source_snapshot_hash(golden_snapshot())
    assert re.fullmatch(r"[0-9a-f]{64}", detail.source_snapshot_hash)
    assert len(reports) == 1
    assert reports[0].headline == "本月支出上升且结构集中"
    assert reports[0].total_spending_display == "¥16,547.30"


async def test_report_ownership_isolation_returns_not_found(app, client) -> None:  # type: ignore[no-untyped-def]
    artifact, _, _ = await persist_golden_report(app, user_id="another-user")

    response = await client.get(f"/api/v1/reports/{artifact.report_id}")
    listing = await client.get("/api/v1/reports")

    assert response.status_code == 404
    assert listing.status_code == 200
    assert listing.json() == []
    async with app.state.test_session_factory() as session:
        try:
            await ReportService(session).get_report_for_user(
                artifact.report_id,
                user_id="dev-user-001",
            )
        except ReportNotFoundError:
            pass
        else:
            raise AssertionError("Cross-user report lookup must fail closed")


async def test_report_api_uses_exact_decimal_strings_and_lightweight_list(app, client) -> None:  # type: ignore[no-untyped-def]
    artifact, conversation, _ = await persist_golden_report(app)

    detail_response = await client.get(f"/api/v1/reports/{artifact.report_id}")
    list_response = await client.get(
        "/api/v1/reports",
        params={"conversation_id": str(conversation.conversation_id)},
    )

    assert detail_response.status_code == 200
    body = detail_response.json()
    overview = body["content"]["overview"]
    comparison = body["content"]["period_comparison"]
    assert overview["total_spending"] == "16547.30"
    assert overview["total_spending_display"] == "¥16,547.30"
    assert comparison["previous_spending"] == "9333.20"
    assert comparison["absolute_change"] == "7214.10"
    assert comparison["absolute_change_display"] == "+¥7,214.10"
    assert comparison["percentage_change"] == ("77.29503278618265975228217546")
    assert comparison["percentage_change_display"] == "+77.3%"
    assert body["source_snapshot_hash"] == source_snapshot_hash(golden_snapshot())

    assert list_response.status_code == 200
    items = list_response.json()
    assert len(items) == 1
    assert "content" not in items[0]
    assert items[0]["total_spending_display"] == "¥16,547.30"


async def test_report_content_cannot_be_overwritten_and_pagination_is_validated(
    app, client
) -> None:  # type: ignore[no-untyped-def]
    artifact, _, _ = await persist_golden_report(app)

    for method in ("post", "put", "patch"):
        response = await client.request(
            method.upper(),
            f"/api/v1/reports/{artifact.report_id}",
            json={},
        )
        assert response.status_code == 405
    assert (await client.get("/api/v1/reports", params={"limit": 0})).status_code == 422
    assert (await client.get("/api/v1/reports", params={"limit": 101})).status_code == 422
    assert (await client.get("/api/v1/reports", params={"offset": -1})).status_code == 422


def test_snapshot_hash_is_canonical_and_stable() -> None:
    snapshot = golden_snapshot()
    reordered = FinancialAnalysisSnapshot.model_validate(
        json.loads(json.dumps(snapshot.model_dump(mode="json"), sort_keys=True))
    )

    assert source_snapshot_hash(snapshot) == source_snapshot_hash(reordered)


async def test_report_delete_restore_preserves_snapshot_and_hides_conversation_entry(app, client):
    from banking_api.persistence.models import ReportModel, TaskModel

    artifact, conversation, accepted = await persist_golden_report(app)
    url = f"/api/v1/reports/{artifact.report_id}"
    original = (await client.get(url)).json()
    async with app.state.test_session_factory() as session:
        task = await session.get(TaskModel, accepted.task_id)
        task.output_json = {
            "report_id": str(artifact.report_id),
            "requested_output": "MONTHLY_REPORT",
        }
        await session.commit()

    assert (await client.delete(url)).status_code == 204
    assert (await client.delete(url)).status_code == 204
    assert (await client.get(url)).status_code == 404
    assert (await client.get("/api/v1/reports")).json() == []
    assert (
        await client.get(
            "/api/v1/reports", params={"conversation_id": str(conversation.conversation_id)}
        )
    ).json() == []
    trash = (await client.get("/api/v1/reports?deleted=true")).json()
    assert [item["report_id"] for item in trash] == [str(artifact.report_id)]
    assert trash[0]["deleted_at"]
    async with app.state.test_session_factory() as session:
        stored = await session.get(ReportModel, artifact.report_id)
        assert stored.content_json == original["content"]
        assert stored.source_snapshot_hash == original["source_snapshot_hash"]
        task = await session.get(TaskModel, accepted.task_id)
        assert task.output_json["report_deleted"] is True

    assert (await client.post(f"{url}/restore")).status_code == 204
    assert (await client.post(f"{url}/restore")).status_code == 204
    restored = (await client.get(url)).json()
    assert restored == original
    assert len((await client.get("/api/v1/reports")).json()) == 1
    assert (await client.get("/api/v1/reports?deleted=true")).json() == []
    async with app.state.test_session_factory() as session:
        task = await session.get(TaskModel, accepted.task_id)
        assert task.output_json["report_deleted"] is False


async def test_report_delete_and_restore_cannot_access_another_user(app, client):
    artifact, _, _ = await persist_golden_report(app, user_id="another-user")
    url = f"/api/v1/reports/{artifact.report_id}"
    assert (await client.delete(url)).status_code == 404
    assert (await client.post(f"{url}/restore")).status_code == 404
    assert (await client.get("/api/v1/reports?deleted=true")).json() == []
    async with app.state.test_session_factory() as session:
        service = ReportService(session)
        await service.get_report_for_user(artifact.report_id, user_id="another-user")
        await service.set_deleted(artifact.report_id, user_id="another-user", deleted=True)
        await session.commit()
    assert (await client.post(f"{url}/restore")).status_code == 404


async def test_report_account_names_are_scoped_display_metadata(app, client):
    artifact, _, _ = await persist_golden_report(app)
    body = (await client.get(f"/api/v1/reports/{artifact.report_id}")).json()
    assert body["account_names"] == {
        "acc_salary": "工资卡",
        "acc_credit": "信用卡",
        "acc_travel": "旅行卡",
    }
    assert body["content"] == artifact.content.model_dump(mode="json")
    assert body["source_snapshot_hash"] == artifact.source_snapshot_hash
