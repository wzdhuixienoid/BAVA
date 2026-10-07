import asyncio
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import async_sessionmaker

from banking_api.api.dependencies import EventBusDependency, PrincipalDependency, SessionDependency
from banking_api.persistence.repositories.conversations import ConversationRepository

router = APIRouter(prefix="/events", tags=["events"])


@router.get("")
async def stream_events(
    request: Request,
    session: SessionDependency,
    principal: PrincipalDependency,
    bus: EventBusDependency,
    conversation_id: Annotated[UUID, Query()],
) -> StreamingResponse:
    conversation = await ConversationRepository(session).get_for_user(
        conversation_id, principal.user_id
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="未找到该对话")

    stream_sessions = async_sessionmaker(session.bind, expire_on_commit=False)

    async def event_stream() -> AsyncIterator[str]:
        async with bus.subscribe(conversation_id) as queue:
            yield ": connected\n\n"
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    async with stream_sessions() as check_session:
                        current = await ConversationRepository(check_session).get_for_user(
                            conversation_id, principal.user_id
                        )
                    if current is None:
                        yield "event: conversation.deleted\ndata: {}\n\n"
                        return
                    yield ": keep-alive\n\n"
                    continue
                payload = event.model_dump_json()
                yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {payload}\n\n"
                if event.event_type == "conversation.deleted":
                    return

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
