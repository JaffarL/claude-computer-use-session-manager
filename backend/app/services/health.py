from collections.abc import AsyncIterator, Awaitable, Callable

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import get_settings
from app.db.session import get_engine
from app.runtime import RuntimeProvider, get_runtime_provider
from app.schemas.health import ComponentHealth


class HealthService:
    def __init__(
        self,
        engine: AsyncEngine,
        redis_client: Redis,
        runtime_provider: RuntimeProvider | None = None,
    ) -> None:
        self._engine = engine
        self._redis = redis_client
        self._runtime_provider = runtime_provider

    async def check_dependencies(self) -> dict[str, ComponentHealth]:
        """独立检查依赖，返回可供人和编排器理解的状态。"""
        checks: dict[str, Callable[[], Awaitable[None]]] = {
            "postgresql": self._check_database,
            "redis": self._check_redis,
        }
        if self._runtime_provider is not None:
            checks["docker"] = self._check_runtime
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

    async def _check_runtime(self) -> None:
        if self._runtime_provider is not None:
            await self._runtime_provider.list_managed()


async def get_health_service() -> AsyncIterator[HealthService]:
    settings = get_settings()
    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        runtime_provider = get_runtime_provider() if settings.runtime_provider == "docker" else None
        yield HealthService(get_engine(), redis_client, runtime_provider)
    finally:
        await redis_client.aclose()
