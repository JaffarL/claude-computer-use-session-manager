import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from app.runtime.base import RuntimeHandle, RuntimeInfo, RuntimeProvider, VncAccess


class FakeRuntimeProvider:
    """无需 Docker 桌面的确定性运行时，用于 API 开发与 CI。"""

    def __init__(self) -> None:
        self.active_runtime_ids: set[str] = set()
        self.session_ids: dict[str, uuid.UUID] = {}
        self.expires_at: dict[str, datetime] = {}

    async def create(self, session_id: uuid.UUID, expires_at: datetime) -> RuntimeHandle:
        runtime_id = f"fake-{session_id}"
        self.active_runtime_ids.add(runtime_id)
        self.session_ids[runtime_id] = session_id
        self.expires_at[runtime_id] = expires_at
        return RuntimeHandle(runtime_id=runtime_id)

    async def stop(self, runtime_id: str) -> None:
        self.active_runtime_ids.discard(runtime_id)

    async def delete(self, runtime_id: str) -> None:
        self.active_runtime_ids.discard(runtime_id)
        self.session_ids.pop(runtime_id, None)
        self.expires_at.pop(runtime_id, None)

    async def inspect(self, runtime_id: str) -> RuntimeInfo | None:
        session_id = self.session_ids.get(runtime_id)
        if session_id is None:
            return None
        return RuntimeInfo(
            runtime_id=runtime_id,
            session_id=session_id,
            status="running" if runtime_id in self.active_runtime_ids else "exited",
            expires_at=self.expires_at[runtime_id],
        )

    async def list_managed(self) -> list[RuntimeInfo]:
        items: list[RuntimeInfo] = []
        for runtime_id in self.session_ids:
            info = await self.inspect(runtime_id)
            if info is not None:
                items.append(info)
        return items

    async def issue_vnc_access(self, runtime_id: str) -> VncAccess:
        if runtime_id not in self.active_runtime_ids:
            raise RuntimeError("运行时不可用。")
        expires_at = datetime.now(UTC) + timedelta(minutes=2)
        return VncAccess(
            url=f"http://localhost/fake-vnc/{runtime_id}",
            expires_at=expires_at,
        )

    async def close(self) -> None:
        return


@lru_cache
def get_runtime_provider() -> RuntimeProvider:
    """按配置选择 CI fake 或真实 Docker 运行时。"""
    from app.core.config import get_settings
    from app.runtime.docker_runtime import DockerRuntimeProvider

    settings = get_settings()
    if settings.runtime_provider == "docker":
        return DockerRuntimeProvider(
            namespace=settings.runtime_namespace,
            image=settings.sandbox_image,
            public_host=settings.sandbox_public_host,
            memory_limit=settings.sandbox_memory_limit,
            nano_cpus=settings.sandbox_nano_cpus,
            pids_limit=settings.sandbox_pids_limit,
            shm_size=settings.sandbox_shm_size,
            startup_timeout_seconds=settings.sandbox_startup_timeout_seconds,
            vnc_access_ttl_seconds=settings.vnc_access_ttl_seconds,
        )
    return FakeRuntimeProvider()


async def close_runtime_provider() -> None:
    if get_runtime_provider.cache_info().currsize:
        await get_runtime_provider().close()
        get_runtime_provider.cache_clear()
