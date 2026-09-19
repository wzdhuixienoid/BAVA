from fastapi import APIRouter

from banking_api.api.routes import conversations, events, tasks

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(conversations.router)
api_router.include_router(tasks.router)
api_router.include_router(events.router)

