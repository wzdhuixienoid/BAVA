from fastapi import APIRouter

from banking_api.api.routes import (
    conversations,
    events,
    operations,
    reports,
    subscriptions,
    tasks,
    workflows,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(conversations.router)
api_router.include_router(tasks.router)
api_router.include_router(events.router)
api_router.include_router(reports.router)
api_router.include_router(workflows.router)
api_router.include_router(operations.router)
api_router.include_router(subscriptions.router)
