import uuid
from functools import lru_cache

from app.runtime.base import RuntimeHandle


class FakeRuntimeProvider:
    """无需 Docker 桌面的确定性运行时，用于 API 开发与 CI。"""

    def __init__(self) -> None:
        self.active_runtime_ids: set[str] = set()

    async def create(self, session_id: uuid.UUID) -> RuntimeHandle:
        runtime_id = f"fake-{session_id}"
        self.active_runtime_ids.add(runtime_id)
        return RuntimeHandle(runtime_id=runtime_id)

    async def stop(self, runtime_id: str) -> None:
        self.active_runtime_ids.discard(runtime_id)

    async def delete(self, runtime_id: str) -> None:
        self.active_runtime_ids.discard(runtime_id)


@lru_cache
def get_runtime_provider() -> FakeRuntimeProvider:
    """当前阶段默认使用 fake；Docker 实现在隔离运行时里程碑接入。"""
    return FakeRuntimeProvider()
