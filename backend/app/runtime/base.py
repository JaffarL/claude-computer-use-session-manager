import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RuntimeHandle:
    """运行时提供者返回的稳定标识。"""

    runtime_id: str


class RuntimeProvider(Protocol):
    """桌面运行时边界，后续可替换为 Docker 或 Kubernetes。"""

    async def create(self, session_id: uuid.UUID) -> RuntimeHandle: ...

    async def stop(self, runtime_id: str) -> None: ...

    async def delete(self, runtime_id: str) -> None: ...
