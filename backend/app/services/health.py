from collections.abc import AsyncIterator, Awaitable, Callable

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import get_settings
from app.db.session import get_engine
from app.schemas.health import ComponentHealth


class HealthService:
    def __init__(self, engine: AsyncEngine, redis_client: Redis) -> None:
        self._engine = engine
        self._redis = redis_client

    async def check_dependencies(self) -> dict[str, ComponentHealth]:
        """独立检查依赖，返回可供人和编排器理解的状态。"""
        checks: dict[str, Callable[[], Awaitable[None]]] = {
            "postgresql": self._check_database,
            "redis": self._check_redis,
        }
        results: dict[str, ComponentHealth] = {}
        for name, check in checks.items():
            try:
                await check()
                results[name] = ComponentHealth(status="正常")
            except Exception as exc:  # 健康接口必须汇总所有依赖的失败信息
                results[name] = ComponentHealth(
                    status="不可用",
                    detail=type(exc).__name__,
                )
        return results

    async def _check_database(self) -> None:
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def _check_redis(self) -> None:
        await self._redis.ping()


async def get_health_service() -> AsyncIterator[HealthService]:
    settings = get_settings()
    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield HealthService(get_engine(), redis_client)
    finally:
        await redis_client.aclose()
