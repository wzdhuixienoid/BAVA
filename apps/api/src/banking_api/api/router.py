from fastapi import APIRouter

from banking_api.api.routes import (
    aa,
    conversations,
    dashboard,
    demo,
    events,
    operations,
    payees,
    plans,
    reports,
    schedules,
    security,
    subscriptions,
    tasks,
    workflows,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(conversations.router)
api_router.include_router(dashboard.router)
api_router.include_router(demo.router)
api_router.include_router(tasks.router)
api_router.include_router(events.router)
api_router.include_router(reports.router)
api_router.include_router(workflows.router)
api_router.include_router(operations.router)
api_router.include_router(subscriptions.router)
api_router.include_router(security.router)
api_router.include_router(plans.router)

api_router.include_router(payees.router)

api_router.include_router(schedules.router)

api_router.include_router(aa.router)
