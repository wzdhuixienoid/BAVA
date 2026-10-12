from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select

from banking_api.api.dependencies import (
    EventBusDependency,
    PrincipalDependency,
    SessionDependency,
    TransferWorkflowEngineDependency,
)
from banking_api.application.workflow_service import WorkflowService
from banking_api.domain.account import AccountBalanceResult
from banking_api.domain.enums import (
    ExecutorType,
    MessageRole,
    RequestedOutput,
    RuntimeBackend,
    TaskStatus,
)
from banking_api.domain.workflow import Workflow
from banking_api.knowledge.wealth import KeywordWealthKnowledge
from banking_api.mock_bank.service import AccountNotFoundError
from banking_api.persistence.repositories.conversations import ConversationRepository
from banking_api.persistence.repositories.messages import MessageRepository
from banking_api.persistence.repositories.tasks import TaskRepository
from banking_api.runtime.event_publisher import EventPublisher
from banking_api.wealth.calculation import WealthError
from banking_api.wealth.models import WealthDocument, WealthOrder
from banking_api.wealth.schemas import (
    AssessmentInput,
    CompareInput,
    RecommendationInput,
    WealthAnalysis,
    WealthAnalysisInput,
    WealthAssessmentResult,
    WealthDraftInput,
    WealthEditInput,
    WealthEvidence,
    WealthFeatureStatus,
    WealthKnowledgeResult,
    WealthOrderResult,
    WealthPositionResult,
    WealthProductResult,
    WealthRecommendationResult,
)
from banking_api.wealth.service import QUESTIONS, WealthService
from banking_api.wealth.workflow import WealthWorkflow, wealth_workflow


def enabled():
    from banking_api.wealth.availability import mock_execution_allowed

    if not mock_execution_allowed():
        raise HTTPException(404, detail="模拟理财尚未启用")


router = APIRouter(prefix="/wealth", tags=["wealth"], dependencies=[Depends(enabled)])


@router.get("/status", response_model=WealthFeatureStatus)
async def status(principal: PrincipalDependency, session: SessionDependency, request: Request):
    from banking_api.wealth.availability import feature_status
    from banking_api.wealth.calculation import utc
    from banking_api.wealth.catalog import digest
    from banking_api.wealth.models import WealthNav, WealthProduct

    versions = (
        await session.execute(
            select(WealthProduct.product_id, WealthProduct.current_version).order_by(
                WealthProduct.product_id
            )
        )
    ).all()
    # Latest published pricing changes refresh product NAV without downloading static documents.
    published = (
        await session.execute(
            select(WealthNav.product_id, func.max(WealthNav.nav_date))
            .where(WealthNav.published_at <= utc(request.app.state.wealth_provider.clock()))
            .group_by(WealthNav.product_id)
            .order_by(WealthNav.product_id)
        )
    ).all()
    return {
        **feature_status(),
        "pricing_version": digest([[pid, day.isoformat()] for pid, day in published]),
        "catalog_version": digest([list(v) for v in versions]),
        "questionnaire_version": "mock-v1",
    }


def service(session, request):
    return WealthService(
        session,
        request.app.state.transfer_provider.balances,
        request.app.state.wealth_provider.clock,
    )


@router.get("/products", response_model=list[WealthProductResult])
async def products(session: SessionDependency, principal: PrincipalDependency, request: Request):
    return await service(session, request).products(principal.user_id)


@router.get("/products/{product_id}", response_model=WealthProductResult)
async def product(
    product_id: str, session: SessionDependency, principal: PrincipalDependency, request: Request
):
    return await service(session, request).product(product_id, principal.user_id)


@router.post("/compare", response_model=list[WealthProductResult])
async def compare(
    body: CompareInput, session: SessionDependency, principal: PrincipalDependency, request: Request
):
    return await service(session, request).compare(body.product_ids, principal.user_id)


@router.get("/product-profiles/{product_id}/{profile_version}", response_model=WealthEvidence)
async def product_profile(
    product_id: str,
    profile_version: str,
    session: SessionDependency,
    principal: PrincipalDependency,
    request: Request,
):
    from banking_api.wealth.design_profiles import design_evidence

    evidence = design_evidence(
        await service(session, request).product(product_id, principal.user_id)
    )
    if evidence is None or evidence.version != profile_version:
        raise HTTPException(404, detail="未找到该版本的模拟设计资料")
    return evidence


@router.post("/analysis", response_model=WealthAnalysis)
async def analysis(
    body: WealthAnalysisInput,
    session: SessionDependency,
    principal: PrincipalDependency,
    request: Request,
):
    from banking_api.wealth.generation import generate_analysis

    try:
        return await generate_analysis(service(session, request), body, principal, request.app)
    except AccountNotFoundError:
        raise WealthError("NOT_FOUND", "未找到本人账户") from None


@router.get("/snapshots/{task_id}", response_model=WealthAnalysis)
async def snapshot(task_id: UUID, session: SessionDependency, principal: PrincipalDependency):
    task = await TaskRepository(session).get_for_user(task_id, principal.user_id)
    if not task or not task.output_json or not task.output_json.get("wealth_analysis"):
        raise WealthError("NOT_FOUND", "未找到本人分析")
    return WealthAnalysis.model_validate(task.output_json["wealth_analysis"])


@router.post("/recommendations", response_model=WealthRecommendationResult)
async def recommendations(
    body: RecommendationInput,
    session: SessionDependency,
    principal: PrincipalDependency,
    request: Request,
):
    try:
        from banking_api.wealth.advisory import WealthAdvisoryService

        return await WealthAdvisoryService(service(session, request)).recommendation(
            principal.user_id, body
        )
    except (KeyError, ValueError, AccountNotFoundError) as exc:
        if isinstance(exc, WealthError):
            raise
        raise WealthError("NOT_FOUND", "未找到本人账户") from None


@router.get("/questionnaire")
async def questionnaire(principal: PrincipalDependency):
    return {
        "version": "mock-v1",
        "notice": "Mock规则，有效期12个月，不代表法定标准。请本人选择，模型不能代填。",
        "questions": [
            {"label": label, "options": options.split("／")} for label, options in QUESTIONS
        ],
    }


@router.get("/risk-assessments/current", response_model=WealthAssessmentResult | None)
async def current_assessment(
    session: SessionDependency, principal: PrincipalDependency, request: Request
):
    svc = service(session, request)
    a = await svc.current_assessment(principal.user_id)
    return svc.assessment_result(a) if a else None


@router.post("/risk-assessments", response_model=WealthAssessmentResult)
async def save_assessment(
    body: AssessmentInput,
    session: SessionDependency,
    principal: PrincipalDependency,
    request: Request,
):
    from banking_api.security.guard import SecurityGuardService
    from banking_api.wealth.availability import require_new_business

    require_new_business()
    await SecurityGuardService(session).require_write_allowed(principal.user_id)
    result = await service(session, request).save_assessment(principal.user_id, body)
    await session.commit()
    return result


@router.get("/knowledge/search", response_model=list[WealthKnowledgeResult])
async def knowledge(
    session: SessionDependency,
    principal: PrincipalDependency,
    request: Request,
    query: Annotated[str, Query(min_length=1, max_length=300)],
    product_id: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
    order_id: UUID | None = None,
    version_id: Annotated[str | None, Query(max_length=80)] = None,
):
    version = version_id
    if order_id:
        order = await session.scalar(
            select(WealthOrder).where(
                WealthOrder.order_id == order_id, WealthOrder.user_id == principal.user_id
            )
        )
        if not order or (product_id and order.product_id != product_id):
            raise WealthError("NOT_FOUND", "未找到本人订单")
        if version_id and version_id != order.version_id:
            raise WealthError("VERSION_MISMATCH", "指定版本与本人订单绑定资料不一致")
        product_id, version = order.product_id, order.version_id
    if version and not product_id:
        raise WealthError("PRODUCT_REQUIRED", "指定资料版本时请提供产品")
    return await KeywordWealthKnowledge(service(session, request)).search(
        product_id, query, version
    )


@router.get("/documents/{document_id}", response_model=WealthKnowledgeResult)
async def document(document_id: str, session: SessionDependency, principal: PrincipalDependency):
    d = await session.get(WealthDocument, document_id)
    if not d:
        raise WealthError("NOT_FOUND", "未找到资料")
    from banking_api.wealth.catalog import digest
    from banking_api.wealth.models import WealthProductVersion

    version = await session.get(WealthProductVersion, d.version_id)
    if (
        not version
        or digest(d.content) != d.content_hash
        or version.terms.get("document_hashes", {}).get(d.document_id) != d.content_hash
    ):
        raise WealthError("PRODUCT_DOCUMENT_CONFLICT", "产品资料异常，无法作为分析依据")
    return WealthKnowledgeResult(
        document_id=d.document_id,
        version=d.version,
        section=d.section,
        source=d.source,
        content=d.content,
    )


@router.get("/positions", response_model=list[WealthPositionResult])
async def positions(session: SessionDependency, principal: PrincipalDependency, request: Request):
    return await service(session, request).positions(principal.user_id)


@router.get("/orders", response_model=list[WealthOrderResult])
async def orders(session: SessionDependency, principal: PrincipalDependency, request: Request):
    return await service(session, request).orders(principal.user_id)


@router.get("/orders/{order_id}", response_model=WealthOrderResult)
async def order(
    order_id: UUID, session: SessionDependency, principal: PrincipalDependency, request: Request
):
    o = await session.scalar(
        select(WealthOrder).where(
            WealthOrder.order_id == order_id, WealthOrder.user_id == principal.user_id
        )
    )
    if not o:
        raise WealthError("NOT_FOUND", "未找到本人订单")
    return await service(session, request).order_result(o)


@router.post("/workflows", response_model=Workflow)
async def create_workflow(
    body: WealthDraftInput,
    session: SessionDependency,
    principal: PrincipalDependency,
    request: Request,
    bus: EventBusDependency,
    engine: TransferWorkflowEngineDependency,
):
    from banking_api.persistence.models import WorkflowModel
    from banking_api.security.guard import SecurityGuardService, acquire_security_user_lock
    from banking_api.wealth.availability import require_new_business

    await acquire_security_user_lock(session, principal.user_id)
    if body.creation_key:
        existing = await session.scalar(
            select(WorkflowModel).where(
                WorkflowModel.user_id == principal.user_id,
                WorkflowModel.workflow_type.in_(["WEALTH_PURCHASE", "WEALTH_REDEEM"]),
                WorkflowModel.state_json["draft"]["creation_key"].as_string()
                == str(body.creation_key),
            )
        )
        if existing:
            return await WorkflowService(session, bus, engine)._to_workflow(existing)
    require_new_business()
    await SecurityGuardService(session).require_write_allowed(principal.user_id)
    if body.direction == "PURCHASE":
        await service(session, request).require_assessment(principal.user_id)
    if body.conversation_id:
        conversation = await ConversationRepository(session).get_for_user(
            body.conversation_id, principal.user_id
        )
        if not conversation:
            raise WealthError("NOT_FOUND", "未找到本人对话")
    else:
        conversation = await ConversationRepository(session).create(
            user_id=principal.user_id, title="模拟理财交易"
        )
    conversation_id = conversation.conversation_id
    message = await MessageRepository(session).create(
        conversation_id=conversation_id,
        role=MessageRole.USER,
        content="页面发起模拟理财申购" if body.direction == "PURCHASE" else "页面发起模拟理财赎回",
    )
    draft = body.model_dump(mode="json", exclude={"conversation_id"})
    task = await TaskRepository(session).create(
        conversation_id=conversation_id,
        user_id=principal.user_id,
        task_type=f"WEALTH_{body.direction}",
        input_data={"message_id": str(message.message_id), "wealth_draft": draft},
        runtime_backend=RuntimeBackend.LANGGRAPH,
    )
    task.executor_type, task.executor_id, task.requested_output = (
        ExecutorType.WORKFLOW,
        f"workflow:wealth-{body.direction.lower()}",
        RequestedOutput.WORKFLOW,
    )
    model = await wealth_workflow(body.direction, session, engine.wealth_engine.balances).create(
        principal.user_id, conversation_id, task.task_id, draft
    )
    task.status, task.next_run_at = TaskStatus.WAITING_USER, None
    task.output_json = {"workflow_id": str(model.workflow_id), "route": f"WEALTH_{body.direction}"}
    await EventPublisher(session).persist(
        event_type="task.created",
        conversation_id=conversation_id,
        task_id=task.task_id,
        data={"task_id": str(task.task_id), "status": task.status.value},
    )
    await session.commit()
    return await WorkflowService(session, bus, engine)._to_workflow(model)


@router.get("/workflows", response_model=list[Workflow])
async def list_wealth_workflows(
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
    engine: TransferWorkflowEngineDependency,
):
    from banking_api.persistence.models import WorkflowModel

    models = (
        await session.scalars(
            select(WorkflowModel)
            .where(
                WorkflowModel.user_id == principal.user_id,
                WorkflowModel.workflow_type.in_(["WEALTH_PURCHASE", "WEALTH_REDEEM"]),
            )
            .order_by(WorkflowModel.updated_at.desc())
            .limit(100)
        )
    ).all()
    service = WorkflowService(session, bus, engine)
    return [await service._to_workflow(model) for model in models]


# Selection/quantity mutations use one versioned action and invalidate all prior authority.
@router.post("/workflows/{workflow_id}/actions/edit", response_model=Workflow)
async def edit_workflow(
    workflow_id: UUID,
    body: WealthEditInput,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
    engine: TransferWorkflowEngineDependency,
):
    from banking_api.api.routes.workflows import _raise_action_error
    from banking_api.application.workflow_service import (
        WorkflowNotFoundError,
        WorkflowVersionConflictError,
    )
    from banking_api.security.guard import SecurityWriteLockedError

    try:
        model = await WealthWorkflow(session, engine.wealth_engine.balances).edit(
            workflow_id, principal.user_id, body
        )
        return await WorkflowService(session, bus, engine)._to_workflow(model)
    except (WorkflowNotFoundError, WorkflowVersionConflictError, SecurityWriteLockedError) as exc:
        _raise_action_error(exc)


@router.get("/accounts", response_model=list[AccountBalanceResult])
async def wealth_accounts(
    session: SessionDependency, principal: PrincipalDependency, request: Request
):
    from datetime import UTC, datetime

    balances = request.app.state.transfer_provider.balances
    return [
        AccountBalanceResult(
            **(
                balances._bank.get_balance(a["account_id"], user_id=principal.user_id)
                | {
                    "balance": await balances.in_session(
                        session, principal.user_id, a["account_id"]
                    )
                }
            ),
            as_of=datetime.now(UTC),
        )
        for a in balances._bank.list_accounts(user_id=principal.user_id)
        if a["currency"] == "CNY"
        and a["account_type"] in {"DEBIT", "SAVINGS"}
        and a["status"] == "ACTIVE"
    ]
