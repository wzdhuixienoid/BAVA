from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from banking_api.api.dependencies import (
    EventBusDependency,
    PrincipalDependency,
    SessionDependency,
    TaskRunnerDependency,
)
from banking_api.application.conversation_service import (
    ConversationActiveError,
    ConversationNotFoundError,
    ConversationService,
)
from banking_api.domain.conversation import (
    Conversation,
    ConversationCreate,
    ConversationDetail,
    ConversationRename,
)
from banking_api.domain.message import MessageAccepted, MessageCreate

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.patch("/{conversation_id}", response_model=Conversation)
async def rename_conversation(
    conversation_id: UUID,
    body: ConversationRename,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
) -> Conversation:
    try:
        return await ConversationService(session, bus).rename(
            conversation_id=conversation_id,
            user_id=principal.user_id,
            title=body.title,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到该对话") from exc


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
    return accepted


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
) -> Response:
    try:
        await ConversationService(session, bus).delete(
            conversation_id=conversation_id, user_id=principal.user_id
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到该对话") from exc
    except ConversationActiveError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CONVERSATION_HAS_ACTIVE_TASKS",
                "message": "该对话还有未结束的任务，请先完成或取消相关流程。",
            },
        ) from exc
    return Response(status_code=204)
