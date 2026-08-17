import uuid

import pytest
from httpx import AsyncClient


async def create_session(client: AsyncClient, title: str = "验收会话") -> dict[str, object]:
    response = await client.post(
        "/api/v1/sessions",
        json={"title": title, "expires_in_seconds": 3600},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_create_get_and_list_sessions(api_client: AsyncClient) -> None:
    created = await create_session(api_client, "  浏览器任务  ")

    assert created["title"] == "浏览器任务"
    assert created["status"] == "READY"
    assert str(created["runtime_id"]).startswith("fake-")
    assert created["version"] == 2

    fetched = await api_client.get(f"/api/v1/sessions/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == created

    listed = await api_client.get("/api/v1/sessions?offset=0&limit=10")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert [item["id"] for item in listed.json()["items"]] == [created["id"]]


@pytest.mark.asyncio
async def test_unknown_session_uses_stable_error_contract(api_client: AsyncClient) -> None:
    response = await api_client.get(f"/api/v1/sessions/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "resource_not_found", "message": "会话不存在。"}}


@pytest.mark.asyncio
async def test_run_idempotency_and_message_persistence(api_client: AsyncClient) -> None:
    created = await create_session(api_client)
    session_id = created["id"]
    headers = {"Idempotency-Key": "demo-run-001"}

    first = await api_client.post(
        f"/api/v1/sessions/{session_id}/runs",
        headers=headers,
        json={"input": "打开示例网站"},
    )
    replay = await api_client.post(
        f"/api/v1/sessions/{session_id}/runs",
        headers=headers,
        json={"input": "这段内容不会生成第二个任务"},
    )

    assert first.status_code == 202
    assert first.json()["status"] == "PENDING"
    assert replay.status_code == 202
    assert replay.json()["id"] == first.json()["id"]
    assert replay.headers["Idempotency-Replayed"] == "true"

    runs = await api_client.get(f"/api/v1/sessions/{session_id}/runs")
    messages = await api_client.get(f"/api/v1/sessions/{session_id}/messages")
    session = await api_client.get(f"/api/v1/sessions/{session_id}")

    assert len(runs.json()["items"]) == 1
    assert messages.json()["items"][0]["content"] == {"text": "打开示例网站"}
    assert messages.json()["items"][0]["sequence"] == 1
    assert session.json()["status"] == "RUNNING"


@pytest.mark.asyncio
async def test_second_active_run_returns_conflict(api_client: AsyncClient) -> None:
    created = await create_session(api_client)
    session_id = created["id"]
    first = await api_client.post(
        f"/api/v1/sessions/{session_id}/runs",
        json={"input": "第一个任务"},
    )

    second = await api_client.post(
        f"/api/v1/sessions/{session_id}/runs",
        json={"input": "第二个任务"},
    )

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "state_conflict"


@pytest.mark.asyncio
async def test_stop_is_idempotent_and_cancels_active_run(api_client: AsyncClient) -> None:
    created = await create_session(api_client)
    session_id = created["id"]
    await api_client.post(
        f"/api/v1/sessions/{session_id}/runs",
        json={"input": "稍后停止"},
    )

    first_stop = await api_client.post(f"/api/v1/sessions/{session_id}/stop")
    second_stop = await api_client.post(f"/api/v1/sessions/{session_id}/stop")
    runs = await api_client.get(f"/api/v1/sessions/{session_id}/runs")

    assert first_stop.status_code == 200
    assert first_stop.json()["status"] == "STOPPED"
    assert second_stop.status_code == 200
    assert second_stop.json()["version"] == first_stop.json()["version"]
    assert runs.json()["items"][0]["status"] == "CANCELLED"
    assert runs.json()["items"][0]["finished_at"] is not None


@pytest.mark.asyncio
async def test_delete_is_soft_delete_and_excludes_session(api_client: AsyncClient) -> None:
    created = await create_session(api_client)
    session_id = created["id"]

    deleted = await api_client.delete(f"/api/v1/sessions/{session_id}")
    fetched = await api_client.get(f"/api/v1/sessions/{session_id}")
    listed = await api_client.get("/api/v1/sessions")

    assert deleted.status_code == 204
    assert deleted.content == b""
    assert fetched.status_code == 404
    assert listed.json()["total"] == 0


@pytest.mark.asyncio
async def test_request_validation_rejects_blank_content(api_client: AsyncClient) -> None:
    blank_title = await api_client.post(
        "/api/v1/sessions",
        json={"title": "   "},
    )
    created = await create_session(api_client)
    blank_input = await api_client.post(
        f"/api/v1/sessions/{created['id']}/runs",
        json={"input": "   "},
    )

    assert blank_title.status_code == 422
    assert blank_input.status_code == 422
