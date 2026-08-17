from fastapi import APIRouter

from app.api.routes import health, sessions

api_router = APIRouter()
api_router.include_router(health.router, tags=["健康检查"])
api_router.include_router(sessions.router, prefix="/api/v1", tags=["会话管理"])
