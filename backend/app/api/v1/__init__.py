"""v1 路由聚合。"""

from fastapi import APIRouter

from app.api.v1 import (
    actions,
    apps,
    auth,
    contacts,
    datasources,
    docs,
    groups,
    runs,
    settings,
    stats,
    tasks,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(apps.router)
api_router.include_router(contacts.router)
api_router.include_router(groups.router)
api_router.include_router(docs.router)
api_router.include_router(datasources.router)
api_router.include_router(tasks.router)
api_router.include_router(runs.router)
api_router.include_router(actions.router)
api_router.include_router(settings.router)
api_router.include_router(stats.router)

__all__ = ["api_router"]
