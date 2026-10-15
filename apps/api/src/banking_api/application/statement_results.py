"""Store validated ledger evidence and render pure statement queries from bank facts."""

import re

from sqlalchemy import select

from banking_api.domain.statement import AccountStatementInput, AccountStatementResult
from banking_api.financial.statement_presentation import render_statement
from banking_api.financial.statement_summary import build_statement_summary
from banking_api.persistence.models import TaskModel
from banking_api.runtime.base import SuccessfulToolResult


def is_statement_continuation(text: str) -> bool:
    return bool(
        re.fullmatch(
            r"(?:请|帮我)?(?:下一页|继续查询|继续查|继续|还有吗|查看更多|查更多|查询下一页)[？?。！!]*",
            text.strip(),
        )
    )


async def continuation_context(session, *, user_id, conversation_id, before):
    task = await session.scalar(
        select(TaskModel)
        .where(
            TaskModel.user_id == user_id,
            TaskModel.conversation_id == conversation_id,
            TaskModel.created_at < before,
            TaskModel.status == "COMPLETED",
        )
        .order_by(TaskModel.created_at.desc(), TaskModel.task_id.desc())
        .limit(1)
    )
    output = task.output_json if task else None
    if (
        not output
        or len(output.get("statement_results", [])) != 1
        or len(output.get("statement_queries", [])) != 1
    ):
        return None
    page = AccountStatementResult.model_validate(output["statement_results"][0])
    query = AccountStatementInput.model_validate(output["statement_queries"][0])
    return {
        "filters": query.model_dump(mode="json"),
        "as_of": page.as_of.isoformat(),
        "next_offset": page.next_offset,
    }


def statement_results(results: list[SuccessfulToolResult]) -> list[AccountStatementResult]:
    return [
        AccountStatementResult.model_validate(r.output)
        for r in results
        if r.capability_id == "account.statement"
    ]


def statement_answer(results: list[SuccessfulToolResult]) -> str:
    return "\n\n".join(render_statement(page) for page in statement_results(results))


def with_statement_analysis(task):
    """Reformat complete historical snapshots without querying or rewriting past facts."""
    output = task.output or {}
    pages = []
    changed = False
    for raw in output.get("statement_results", []):
        page = AccountStatementResult.model_validate(raw)
        if page.summary is None and page.offset == 0 and len(page.transactions) == page.total_count:
            page = page.model_copy(deep=True)
            page.summary = build_statement_summary(
                page.transactions,
                is_transfer=bool(page.transactions)
                and all(r.category == "TRANSFER" for r in page.transactions),
                scope_display="历史查询快照 · 按当时保存的完整记录汇总",
                view=lambda row: row,
            )
            page.answer = render_statement(page)
            changed = True
        pages.append(page)
    return (
        task.model_copy(update={"output": dict(output) | {"statement_results": pages}})
        if changed
        else task
    )
