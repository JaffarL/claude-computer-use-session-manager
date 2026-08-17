from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.schemas.health import HealthResponse
from app.services.health import HealthService, get_health_service

router = APIRouter(prefix="/health")


@router.get("/live", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    """仅验证 API 进程仍能响应请求。"""
    return HealthResponse(status="正常")


@router.get("/ready", response_model=HealthResponse)
async def readiness(
    response: Response,
    service: Annotated[HealthService, Depends(get_health_service)],
) -> HealthResponse:
    """验证 API 的关键依赖是否可用。"""
    components = await service.check_dependencies()
    is_ready = all(item.status == "正常" for item in components.values())
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="正常" if is_ready else "不可用",
        components=components,
    )
