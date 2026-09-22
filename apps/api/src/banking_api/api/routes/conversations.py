from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from banking_api.api.dependencies import (
    EventBusDependency,
    PrincipalDependency,
    SessionDependency,
    TaskRunnerDependency,
)
from banking_api.application.conversation_service import (
    ConversationNotFoundError,
    ConversationService,
)
from banking_api.domain.conversation import Conversation, ConversationCreate, ConversationDetail
from banking_api.domain.message import MessageAccepted, MessageCreate

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", response_model=Conversation, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
) -> Conversation:
    return await ConversationService(session, bus).create(
        user_id=principal.user_id, title=body.title
    )


@router.get("", response_model=list[Conversation])
async def list_conversations(
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
) -> list[Conversation]:
    return await ConversationService(session, bus).list(user_id=principal.user_id)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: UUID,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
) -> ConversationDetail:
    try:
        return await ConversationService(session, bus).get(
            conversation_id=conversation_id, user_id=principal.user_id
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到该对话") from exc


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_message(
    conversation_id: UUID,
    body: MessageCreate,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
    runner: TaskRunnerDependency,
) -> MessageAccepted:
    try:
        accepted = await ConversationService(
            session, bus, runtime_backend=runner.default_backend
        ).accept_message(
            conversation_id=conversation_id,
            user_id=principal.user_id,
            content=body.content,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到该对话") from exc
    background_tasks.add_task(runner.run, accepted.task_id)
    return accepted
