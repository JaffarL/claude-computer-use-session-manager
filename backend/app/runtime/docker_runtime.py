import asyncio
import base64
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import docker
import jwt
from docker.errors import APIError, ImageNotFound, NotFound

from app.runtime.base import RuntimeHandle, RuntimeInfo, VncAccess

logger = logging.getLogger(__name__)

MANAGED_LABEL = "com.jaffar.computer-use.managed"
SESSION_LABEL = "com.jaffar.computer-use.session-id"
EXPIRES_LABEL = "com.jaffar.computer-use.expires-at"
COMPONENT_LABEL = "com.jaffar.computer-use.component"
VNC_PORT = "6080/tcp"


class DockerRuntimeProvider:
    """通过 Docker Engine 为每个逻辑会话创建独立桌面容器。"""

    def __init__(
        self,
        *,
        image: str,
        public_host: str,
        memory_limit: str,
        nano_cpus: int,
        pids_limit: int,
        shm_size: str,
        startup_timeout_seconds: float,
        vnc_access_ttl_seconds: int,
        client: Any | None = None,
    ) -> None:
        self._client = client or docker.from_env()
        self._image = image
        self._public_host = public_host
        self._memory_limit = memory_limit
        self._nano_cpus = nano_cpus
        self._pids_limit = pids_limit
        self._shm_size = shm_size
        self._startup_timeout_seconds = startup_timeout_seconds
        self._vnc_access_ttl_seconds = vnc_access_ttl_seconds
        self._create_locks: dict[uuid.UUID, asyncio.Lock] = {}

    async def create(self, session_id: uuid.UUID, expires_at: datetime) -> RuntimeHandle:
        lock = self._create_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            existing = await self._find_by_session_id(session_id)
            if existing is not None:
                if existing.status != "running":
                    await asyncio.to_thread(existing.start)
                await self._wait_until_healthy(existing)
                return RuntimeHandle(runtime_id=existing.id)

            jwt_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
            name = f"computer-use-session-{session_id.hex}"
            try:
                container = await asyncio.to_thread(
                    self._client.containers.run,
                    self._image,
                    detach=True,
                    name=name,
                    hostname=f"session-{session_id.hex[:12]}",
                    environment={
                        "SESSION_ID": str(session_id),
                        "VNC_JWT_KEY": jwt_key,
                        "DISPLAY_NUM": "1",
                        "WIDTH": "1024",
                        "HEIGHT": "768",
                    },
                    labels={
                        MANAGED_LABEL: "true",
                        SESSION_LABEL: str(session_id),
                        EXPIRES_LABEL: expires_at.isoformat(),
                        COMPONENT_LABEL: "sandbox",
                    },
                    ports={VNC_PORT: ("127.0.0.1", 0)},
                    init=True,
                    mem_limit=self._memory_limit,
                    nano_cpus=self._nano_cpus,
                    pids_limit=self._pids_limit,
                    shm_size=self._shm_size,
                    cap_drop=["ALL"],
                    security_opt=["no-new-privileges:true"],
                )
            except ImageNotFound as exc:
                raise RuntimeError(f"找不到 sandbox 镜像：{self._image}") from exc
            except APIError as exc:
                if getattr(exc.response, "status_code", None) == 409:
                    container = await asyncio.to_thread(self._client.containers.get, name)
                else:
                    raise RuntimeError("Docker 创建 sandbox 失败。") from exc

            try:
                await self._wait_until_healthy(container)
            except Exception:
                await self._remove_container(container)
                raise
            return RuntimeHandle(runtime_id=container.id)

    async def stop(self, runtime_id: str) -> None:
        container = await self._get_container(runtime_id)
        if container is None:
            return
        await asyncio.to_thread(container.reload)
        if container.status == "running":
            await asyncio.to_thread(container.stop, timeout=10)

    async def delete(self, runtime_id: str) -> None:
        container = await self._get_container(runtime_id)
        if container is not None:
            await self._remove_container(container)

    async def inspect(self, runtime_id: str) -> RuntimeInfo | None:
        container = await self._get_container(runtime_id)
        if container is None:
            return None
        await asyncio.to_thread(container.reload)
        return self._to_runtime_info(container)

    async def list_managed(self) -> list[RuntimeInfo]:
        containers = await asyncio.to_thread(
            self._client.containers.list,
            all=True,
            filters={"label": f"{MANAGED_LABEL}=true"},
        )
        result: list[RuntimeInfo] = []
        for container in containers:
            try:
                result.append(self._to_runtime_info(container))
            except (KeyError, TypeError, ValueError):
                logger.warning("忽略标签损坏的托管容器。", extra={"runtime_id": container.id})
        return result

    async def issue_vnc_access(self, runtime_id: str) -> VncAccess:
        container = await self._get_container(runtime_id)
        if container is None:
            raise RuntimeError("会话桌面容器不存在。")
        await asyncio.to_thread(container.reload)
        health = container.attrs.get("State", {}).get("Health", {}).get("Status")
        if container.status != "running" or health != "healthy":
            raise RuntimeError("会话桌面尚未就绪。")

        environment = container.attrs.get("Config", {}).get("Env", [])
        encoded_key = self._environment_value(environment, "VNC_JWT_KEY")
        if not encoded_key:
            raise RuntimeError("会话桌面缺少 VNC 签名密钥。")
        padding = "=" * (-len(encoded_key) % 4)
        signing_key = base64.urlsafe_b64decode(encoded_key + padding)
        expires_at = datetime.now(UTC) + timedelta(seconds=self._vnc_access_ttl_seconds)
        token = jwt.encode(
            {
                "host": "127.0.0.1",
                "port": 5900,
                "exp": int(expires_at.timestamp()),
                "jti": secrets.token_urlsafe(12),
            },
            signing_key,
            algorithm="HS256",
        )
        host_port = self._host_port(container)
        query = urlencode(
            {
                "autoconnect": "1",
                "resize": "scale",
                "reconnect": "1",
                "token": token,
            }
        )
        return VncAccess(
            url=f"http://{self._public_host}:{host_port}/vnc.html?{query}",
            expires_at=expires_at,
        )

    async def close(self) -> None:
        await asyncio.to_thread(self._client.close)

    async def _find_by_session_id(self, session_id: uuid.UUID) -> Any | None:
        containers = await asyncio.to_thread(
            self._client.containers.list,
            all=True,
            filters={
                "label": [
                    f"{MANAGED_LABEL}=true",
                    f"{SESSION_LABEL}={session_id}",
                ]
            },
        )
        return containers[0] if containers else None

    async def _get_container(self, runtime_id: str) -> Any | None:
        try:
            return await asyncio.to_thread(self._client.containers.get, runtime_id)
        except NotFound:
            return None
        except APIError as exc:
            raise RuntimeError("Docker 查询 sandbox 失败。") from exc

    async def _wait_until_healthy(self, container: Any) -> None:
        deadline = asyncio.get_running_loop().time() + self._startup_timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.to_thread(container.reload)
            state = container.attrs.get("State", {})
            if state.get("Status") in {"exited", "dead"}:
                logs = await asyncio.to_thread(container.logs, tail=50)
                detail = logs.decode(errors="replace")[-2000:]
                raise RuntimeError(f"sandbox 启动失败：{detail}")
            if state.get("Health", {}).get("Status") == "healthy":
                return
            await asyncio.sleep(0.5)
        raise RuntimeError("sandbox 在规定时间内未通过健康检查。")

    async def _remove_container(self, container: Any) -> None:
        try:
            await asyncio.to_thread(container.remove, force=True, v=True)
        except NotFound:
            return
        except APIError as exc:
            raise RuntimeError("Docker 删除 sandbox 失败。") from exc

    @staticmethod
    def _to_runtime_info(container: Any) -> RuntimeInfo:
        labels = container.attrs["Config"]["Labels"]
        return RuntimeInfo(
            runtime_id=container.id,
            session_id=uuid.UUID(labels[SESSION_LABEL]),
            status=container.attrs["State"]["Status"],
            expires_at=datetime.fromisoformat(labels[EXPIRES_LABEL]),
        )

    @staticmethod
    def _environment_value(environment: list[str], name: str) -> str | None:
        prefix = f"{name}="
        return next(
            (item.removeprefix(prefix) for item in environment if item.startswith(prefix)), None
        )

    @staticmethod
    def _host_port(container: Any) -> int:
        bindings = container.attrs.get("NetworkSettings", {}).get("Ports", {}).get(VNC_PORT)
        if not bindings:
            raise RuntimeError("会话桌面没有可用的 noVNC 主机端口。")
        return int(bindings[0]["HostPort"])
