from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.routes.health import get_health_service
from app.main import create_app
from app.schemas.health import ComponentHealth


class HealthyDependencies:
    async def check_dependencies(self) -> dict[str, ComponentHealth]:
        return {
            "postgresql": ComponentHealth(status="正常"),
            "redis": ComponentHealth(status="正常"),
        }


class UnhealthyDependencies:
    async def check_dependencies(self) -> dict[str, ComponentHealth]:
        return {
            "postgresql": ComponentHealth(status="正常"),
            "redis": ComponentHealth(status="不可用", detail="ConnectionError"),
        }


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


@pytest.mark.asyncio
async def test_liveness(client: AsyncClient) -> None:
    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "正常", "components": {}}


@pytest.mark.asyncio
async def test_readiness_when_dependencies_are_healthy(client: AsyncClient) -> None:
    app = create_app()
    app.dependency_overrides[get_health_service] = HealthyDependencies
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        response = await test_client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "正常"


@pytest.mark.asyncio
async def test_readiness_when_a_dependency_is_unavailable() -> None:
    app = create_app()
    app.dependency_overrides[get_health_service] = UnhealthyDependencies
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        response = await test_client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "不可用"
    assert response.json()["components"]["redis"]["detail"] == "ConnectionError"
