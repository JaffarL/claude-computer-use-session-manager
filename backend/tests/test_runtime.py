import asyncio
import base64
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AgentSession
from app.domain import SessionStatus
from app.runtime import FakeRuntimeProvider
from app.runtime.docker_runtime import (
    EXPIRES_LABEL,
    SESSION_LABEL,
    DockerRuntimeProvider,
)
from app.services.runtime_reconciler import RuntimeReconciler


class FakeDockerContainer:
    def __init__(
        self,
        *,
        container_id: str,
        labels: dict[str, str],
        environment: dict[str, str],
        host_port: int,
    ) -> None:
        self.id = container_id
        self.status = "running"
        self.removed = False
        self.attrs = {
            "Config": {
                "Labels": labels,
                "Env": [f"{key}={value}" for key, value in environment.items()],
            },
            "State": {"Status": "running", "Health": {"Status": "healthy"}},
            "NetworkSettings": {
                "Ports": {"6080/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(host_port)}]}
            },
        }

    def reload(self) -> None:
        return

    def start(self) -> None:
        self.status = "running"
        self.attrs["State"]["Status"] = "running"

    def stop(self, timeout: int) -> None:
        assert timeout == 10
        self.status = "exited"
        self.attrs["State"]["Status"] = "exited"

    def remove(self, *, force: bool, v: bool) -> None:
        assert force is True and v is True
        self.removed = True

    def logs(self, *, tail: int) -> bytes:
        assert tail == 50
        return b""


class FakeContainerCollection:
    def __init__(self) -> None:
        self.items: dict[str, FakeDockerContainer] = {}
        self.run_count = 0
        self.last_run_options: dict[str, Any] = {}
        self._lock = threading.Lock()

    def run(self, image: str, **options: Any) -> FakeDockerContainer:
        with self._lock:
            self.run_count += 1
            self.last_run_options = {"image": image, **options}
            container_id = f"runtime-{self.run_count}"
            container = FakeDockerContainer(
                container_id=container_id,
                labels=options["labels"],
                environment=options["environment"],
                host_port=49000 + self.run_count,
            )
            self.items[container_id] = container
            self.items[options["name"]] = container
            return container

    def get(self, runtime_id: str) -> FakeDockerContainer:
        return self.items[runtime_id]

    def list(self, **options: Any) -> list[FakeDockerContainer]:
        assert options["all"] is True
        filters = options["filters"]
        labels = filters.get("label", [])
        if isinstance(labels, str):
            labels = [labels]
        unique = {item.id: item for item in self.items.values() if not item.removed}
        result = list(unique.values())
        for expression in labels:
            key, expected = expression.split("=", 1)
            result = [
                item for item in result if item.attrs["Config"]["Labels"].get(key) == expected
            ]
        return result


class FakeDockerClient:
    def __init__(self) -> None:
        self.containers = FakeContainerCollection()
        self.closed = False

    def close(self) -> None:
        self.closed = True


def make_docker_provider(client: FakeDockerClient) -> DockerRuntimeProvider:
    return DockerRuntimeProvider(
        image="computer-use-sandbox:test",
        public_host="localhost",
        memory_limit="768m",
        nano_cpus=1_000_000_000,
        pids_limit=256,
        shm_size="256m",
        startup_timeout_seconds=1,
        vnc_access_ttl_seconds=120,
        client=client,
    )


@pytest.mark.asyncio
async def test_concurrent_create_is_idempotent_and_applies_limits() -> None:
    client = FakeDockerClient()
    provider = make_docker_provider(client)
    session_id = uuid.uuid4()
    expires_at = datetime.now(UTC) + timedelta(hours=1)

    handles = await asyncio.gather(*(provider.create(session_id, expires_at) for _ in range(20)))

    assert client.containers.run_count == 1
    assert {handle.runtime_id for handle in handles} == {"runtime-1"}
    options = client.containers.last_run_options
    assert options["ports"] == {"6080/tcp": ("127.0.0.1", 0)}
    assert options["mem_limit"] == "768m"
    assert options["nano_cpus"] == 1_000_000_000
    assert options["pids_limit"] == 256
    assert options["shm_size"] == "256m"
    assert options["cap_drop"] == ["ALL"]
    assert options["security_opt"] == ["no-new-privileges:true"]
    assert options["labels"][SESSION_LABEL] == str(session_id)
    assert options["labels"][EXPIRES_LABEL] == expires_at.isoformat()


@pytest.mark.asyncio
async def test_vnc_jwt_is_short_lived_and_bound_to_one_container() -> None:
    client = FakeDockerClient()
    provider = make_docker_provider(client)
    session_id = uuid.uuid4()
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    handle = await provider.create(session_id, expires_at)
    container = client.containers.get(handle.runtime_id)
    encoded_key = next(
        value.split("=", 1)[1]
        for value in container.attrs["Config"]["Env"]
        if value.startswith("VNC_JWT_KEY=")
    )
    signing_key = base64.urlsafe_b64decode(encoded_key + "=" * (-len(encoded_key) % 4))

    access = await provider.issue_vnc_access(handle.runtime_id)
    token = parse_qs(urlparse(access.url).query)["token"][0]
    claims = jwt.decode(token, signing_key, algorithms=["HS256"])

    other_handle = await provider.create(uuid.uuid4(), expires_at)
    other_container = client.containers.get(other_handle.runtime_id)
    other_encoded_key = next(
        value.split("=", 1)[1]
        for value in other_container.attrs["Config"]["Env"]
        if value.startswith("VNC_JWT_KEY=")
    )
    other_signing_key = base64.urlsafe_b64decode(
        other_encoded_key + "=" * (-len(other_encoded_key) % 4)
    )

    assert claims["host"] == "127.0.0.1"
    assert claims["port"] == 5900
    assert 0 < claims["exp"] - int(datetime.now(UTC).timestamp()) <= 120
    assert access.url.startswith("http://localhost:49001/vnc.html?")
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, other_signing_key, algorithms=["HS256"])


@pytest.mark.asyncio
async def test_reconciler_recovers_binding_and_deletes_expired_orphan_runtimes(
    database_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = FakeRuntimeProvider()
    now = datetime.now(UTC)
    recovered_id = uuid.uuid4()
    expired_id = uuid.uuid4()
    orphan_id = uuid.uuid4()
    stopping_id = uuid.uuid4()
    recovered_runtime = await provider.create(recovered_id, now + timedelta(hours=1))
    expired_runtime = await provider.create(expired_id, now - timedelta(seconds=1))
    orphan_runtime = await provider.create(orphan_id, now + timedelta(hours=1))
    stopping_runtime = await provider.create(stopping_id, now + timedelta(hours=1))
    await provider.stop(stopping_runtime.runtime_id)

    async with database_factory() as database_session:
        database_session.add_all(
            [
                AgentSession(
                    id=recovered_id,
                    title="恢复绑定",
                    status=SessionStatus.CREATING.value,
                    runtime_id=None,
                    expires_at=now + timedelta(hours=1),
                ),
                AgentSession(
                    id=expired_id,
                    title="过期清理",
                    status=SessionStatus.READY.value,
                    runtime_id=expired_runtime.runtime_id,
                    expires_at=now - timedelta(seconds=1),
                ),
                AgentSession(
                    id=stopping_id,
                    title="停止恢复",
                    status=SessionStatus.STOPPING.value,
                    runtime_id=stopping_runtime.runtime_id,
                    expires_at=now + timedelta(hours=1),
                ),
            ]
        )
        await database_session.commit()

    await RuntimeReconciler(database_factory, provider).reconcile()

    async with database_factory() as database_session:
        recovered = await database_session.get(AgentSession, recovered_id)
        expired = await database_session.get(AgentSession, expired_id)
        stopping = await database_session.get(AgentSession, stopping_id)
    assert recovered is not None
    assert recovered.runtime_id == recovered_runtime.runtime_id
    assert recovered.status == SessionStatus.READY.value
    assert expired is not None and expired.status == SessionStatus.EXPIRED.value
    assert stopping is not None and stopping.status == SessionStatus.STOPPED.value
    assert await provider.inspect(expired_runtime.runtime_id) is None
    assert await provider.inspect(orphan_runtime.runtime_id) is None
