"""Owner/conversation scoped durable facts; no authorization is inherited."""

import re

from sqlalchemy import select

from banking_api.persistence.models import MessageModel, TaskModel
from banking_api.wealth.schemas import WealthAnalysis, WealthAnalysisInput

ASSESSMENT_UPDATE = re.compile(
    r"(?:完成|做完|测完|重测)(?:了)?(?:风险)?测评|(?:风险)?测评(?:已经|已)?完成|测评做完"
)

FOLLOW_UP = re.compile(
    r"保本|本金|稳健|预算|期限|R[1-5]|不能等周一|为什么.*(?:这|它|第|推荐|选)|第[一二1234]款|首款|这两款|上次|现在.*(?:适合|买)|下周.*用钱|(?:如果|预算|买)\s*\d.*元|每天开放|随时到账|按当前条件重新分析"
)
EDUCATION = re.compile(
    r"最大回撤|业绩比较基准|年化|理财.*存款|净值型|为什么会亏|保证不亏|每天开放.*到账|风险低.*保证"
)


async def latest_analysis(
    session, user_id, conversation_id, *, before=None, require_candidates=False
):
    statement = select(TaskModel).where(
        TaskModel.user_id == user_id,
        TaskModel.conversation_id == conversation_id,
        TaskModel.status.in_(["COMPLETED", "WAITING_USER", "WAITING_EXTERNAL"]),
        TaskModel.executor_id.in_(
            ["agent:wealth-advisor", "workflow:wealth-purchase", "workflow:wealth-redeem"]
        ),
    )
    statement = statement.where(
        TaskModel.output_json["wealth_analysis"]["result_kind"]
        .as_string()
        .in_(
            [
                "RECOMMENDATION",
                "COMPARISON",
                "EXPLANATION",
                "PRODUCT_INTRO",
                "PREPARE_PURCHASE",
                "PREPARE_REDEEM",
                "CATALOGUE",
                "PRODUCT_OVERVIEW",
            ]
        )
    )
    if require_candidates:
        statement = statement.where(
            TaskModel.output_json["wealth_analysis"]["candidates"][0]["fact_id"]
            .as_string()
            .is_not(None)
        )
    if before:
        statement = statement.where(TaskModel.created_at < before)
    # Filter on the JSON key before limiting: unrelated later messages do not erase a snapshot.
    statement = statement.where(
        TaskModel.output_json["wealth_analysis"]["schema_version"]
        .as_string()
        .in_(["wealth-analysis-v1", "wealth-analysis-v2"])
    )
    rows = (
        await session.scalars(
            statement.order_by(TaskModel.created_at.desc(), TaskModel.task_id.desc()).limit(3)
        )
    ).all()
    for row in rows:
        try:
            snapshot = WealthAnalysis.model_validate(row.output_json["wealth_analysis"])
            if snapshot.source_task_id == row.task_id:
                return snapshot
        except (ValueError, KeyError):
            continue
    return None


def analysis_input(text, products, previous=None):
    ids = [p.product_id for p in products if p.name in text or p.name.removeprefix("演示") in text]
    kind = "RECOMMENDATION"
    if EDUCATION.search(text) and not any(
        w in text for w in ("推荐", "适合我", "比较", "对比", "费用差")
    ):
        kind = "EDUCATION"
    if (
        ids
        and re.search(r"费用|手续费|费率|到账|多久|规则|条款|说明书|净值|风险", text)
        and not re.search(r"推荐|适合", text)
    ):
        kind = "COMPARISON"
    if re.search(r"比较(?!\s*(?:多|高|低|好|少|强|大|小))|对比|费用差|这两款", text):
        kind = "COMPARISON"
        if not ids and previous:
            ids = [c.product.product_id for c in previous.candidates][:4]
    elif (
        previous
        and re.search(r"为什么|优势|第一款|第二款|这个|它|上次", text)
        and not re.search(r"现在|下周|用钱|\d[\d,.]*\s*元|重新分析", text)
        and kind != "EDUCATION"
    ):
        kind = "EXPLANATION"
    elif (
        previous
        and re.search(r"现在|下周|用钱|\d[\d,.]*\s*元", text)
        and previous.result_kind == "COMPARISON"
    ):
        kind = "COMPARISON"
        if not ids:
            ids = [c.product.product_id for c in previous.candidates][:4]
    elif re.search(
        r"有什么(?:模拟)?理财|理财(?:产品)?(?:有|都有哪些|有什么)|有哪些|列出|产品列表", text
    ) and not re.search(r"推荐|适合|想买|购买|申购|比较|对比", text):
        kind = "CATALOGUE"
    if (
        ids
        and re.search(r"购买|申购|买入|我要买|想买|要买", text)
        and not re.search(r"比较|对比|为什么|费用|手续费|规则", text)
    ):
        kind = "PRODUCT_INTRO"
    if (
        ASSESSMENT_UPDATE.search(text)
        and previous
        and previous.result_kind == "PRODUCT_INTRO"
        and not ids
    ):
        ids = [c.product.product_id for c in previous.candidates]
        kind = "PRODUCT_INTRO"
    return WealthAnalysisInput(intent=kind, query=text, needs=text, product_ids=ids)


def concise_context(snapshot):
    return {
        "snapshot_id": str(snapshot.snapshot_id),
        "reference_time": snapshot.reference_time.isoformat(),
        "status": snapshot.status,
        "needs": snapshot.needs.model_dump(exclude={"account_id"}),
        "candidate_order": [
            {
                "name": c.product.name,
                "product_id": c.product.product_id,
                "version_id": c.product.version_id,
            }
            for c in snapshot.candidates
        ],
        "notice": "历史快照只用于解释，不代表当前权限或交易授权。",
    }


def trade_reference(text, previous):
    """Resolve only explicit single purchase instructions, without fabricating units/account."""
    reference = re.search(r"(?:申购|购买|买入|买)\s*(第[一二1234]款|首款|这款|这个|它)", text)
    if not reference or re.search(r"适合|推荐|费用|手续费|如果|能买|可以买|比较|为什么", text):
        return text
    candidates = previous.candidates if previous else []
    token = reference[1]
    if token in {"这个", "这款", "它"}:
        if len(candidates) != 1:
            return None
        index = 0
    else:
        index = {
            "第一款": 0,
            "第二款": 1,
            "第1款": 0,
            "第2款": 1,
            "第3款": 2,
            "第4款": 3,
            "首款": 0,
        }[token]
    if index >= len(candidates):
        return None
    return text[: reference.start(1)] + candidates[index].product.name + text[reference.end(1) :]


async def latest_purchase_interest(session, user_id, conversation_id, *, before=None):
    """Recover pre-upgrade assessment-blocked/pending purchase intent without authority."""
    statement = select(TaskModel).where(
        TaskModel.user_id == user_id,
        TaskModel.conversation_id == conversation_id,
        TaskModel.executor_id == "workflow:wealth-purchase",
        TaskModel.status.in_(["COMPLETED", "WAITING_USER"]),
    )
    if before:
        statement = statement.where(TaskModel.created_at < before)
    rows = (await session.scalars(statement.order_by(TaskModel.created_at.desc()).limit(3))).all()
    for row in rows:
        mid = row.input_json.get("message_id")
        if not mid:
            continue
        from uuid import UUID

        try:
            message_id = UUID(str(mid))
        except ValueError:
            continue
        message = await session.get(MessageModel, message_id)
        if message and message.conversation_id == conversation_id:
            return message.content
    return None
