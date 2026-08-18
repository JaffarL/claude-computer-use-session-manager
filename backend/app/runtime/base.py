import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RuntimeHandle:
    """运行时提供者返回的稳定标识。"""

    runtime_id: str


@dataclass(frozen=True, slots=True)
class RuntimeInfo:
    """可用于进程重启后恢复绑定的运行时信息。"""

    runtime_id: str
    session_id: uuid.UUID
    status: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class VncAccess:
    """一次有明确过期时间的 noVNC 访问入口。"""

    url: str
    expires_at: datetime


class RuntimeProvider(Protocol):
    """桌面运行时边界，后续可替换为 Docker 或 Kubernetes。"""

    async def create(self, session_id: uuid.UUID, expires_at: datetime) -> RuntimeHandle: ...

    async def stop(self, runtime_id: str) -> None: ...

    async def delete(self, runtime_id: str) -> None: ...

    async def inspect(self, runtime_id: str) -> RuntimeInfo | None: ...

    async def list_managed(self) -> list[RuntimeInfo]: ...

    async def issue_vnc_access(self, runtime_id: str) -> VncAccess: ...

    async def close(self) -> None: ...
