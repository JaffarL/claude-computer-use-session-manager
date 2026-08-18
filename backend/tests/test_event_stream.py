import asyncio
import json
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents import AgentEventSink, FakeAgentRunner
from app.agents.anthropic_callbacks import AnthropicCallbackAdapter
from app.db.models import AgentRun, AgentSession, ChatMessage, SessionEvent
from app.domain import EventType
from app.events import InMemoryEventBroker
from app.services.event_stream import EventStreamService, encode_heartbeat, encode_sse_event
from app.services.events import EventService
from app.services.run_executor import RunExecutor
from tests.test_session_api import create_session


def parse_sse_data(chunk: str) -> dict[str, Any]:
    data_line = next(line for line in chunk.splitlines() if line.startswith("data: "))
    return json.loads(data_line.removeprefix("data: "))


async def execute_fake_run(
    api_client: AsyncClient,
    database_factory: async_sessionmaker[AsyncSession],
    broker: InMemoryEventBroker,
) -> tuple[uuid.UUID, uuid.UUID]:
    created = await create_session(api_client, "SSE 测试")
    session_id = uuid.UUID(str(created["id"]))
    response = await api_client.post(
        f"/api/v1/sessions/{session_id}/runs",
        json={"input": "检查事件顺序"},
    )
    run_id = uuid.UUID(response.json()["id"])
    executor = RunExecutor(database_factory, broker, FakeAgentRunner(0))
    await executor.execute(run_id)
    return session_id, run_id


@pytest.mark.asyncio
async def test_fake_agent_persists_ordered_events_and_assistant_message(
    api_client: AsyncClient,
    database_factory: async_sessionmaker[AsyncSession],
) -> None:
    broker = InMemoryEventBroker()
    session_id, run_id = await execute_fake_run(api_client, database_factory, broker)

    async with database_factory() as database_session:
        run = await database_session.get(AgentRun, run_id)
        session = await database_session.get(AgentSession, session_id)
        events = list(
            (
                await database_session.scalars(
                    select(SessionEvent)
                    .where(SessionEvent.session_id == session_id)
                    .order_by(SessionEvent.id)
                )
            ).all()
        )
        messages = list(
            (
                await database_session.scalars(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == session_id)
                    .order_by(ChatMessage.sequence)
                )
            ).all()
        )

    assert run is not None and run.status == "COMPLETED"
    assert session is not None and session.status == "READY"
    assert [event.event_type for event in events] == [
        "run.started",
        "assistant.delta",
        "assistant.delta",
        "tool.started",
        "tool.result",
        "screenshot.available",
        "assistant.message",
        "run.completed",
    ]
    assert [message.role for message in messages] == ["USER", "ASSISTANT"]
    assert messages[1].content["text"].startswith("模拟任务已完成")


@pytest.mark.asyncio
async def test_sse_replays_from_last_event_id_and_emits_heartbeat(
    api_client: AsyncClient,
    database_factory: async_sessionmaker[AsyncSession],
) -> None:
    broker = InMemoryEventBroker()
    session_id, _ = await execute_fake_run(api_client, database_factory, broker)
    service = EventStreamService(
        database_factory,
        broker,
        heartbeat_seconds=0.01,
        queue_size=10,
    )

    history = await service.history(session_id, 0)
    assert len(history) == 8
    reconnect_after = history[2].id
    stream = service.stream(session_id, reconnect_after)
    assert await anext(stream) == "retry: 2000\n\n"
    replayed = [parse_sse_data(await anext(stream)) for _ in range(5)]
    assert [event["id"] for event in replayed] == [item.id for item in history[3:]]

    heartbeat = await asyncio.wait_for(anext(stream), timeout=0.2)
    assert heartbeat.startswith("event: heartbeat\n")
    await stream.aclose()


@pytest.mark.asyncio
async def test_sse_receives_event_published_after_connection(
    api_client: AsyncClient,
    database_factory: async_sessionmaker[AsyncSession],
) -> None:
    created = await create_session(api_client, "实时事件测试")
    session_id = uuid.UUID(str(created["id"]))
    broker = InMemoryEventBroker()
    service = EventStreamService(
        database_factory,
        broker,
        heartbeat_seconds=1,
        queue_size=10,
    )
    stream = service.stream(session_id, 0)
    assert await anext(stream) == "retry: 2000\n\n"

    pending_event = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    async with database_factory() as database_session:
        created_event = await EventService(database_session, broker).append(
            session_id=session_id,
            run_id=None,
            event_type=EventType.SESSION_STATUS,
            payload={"status": "READY"},
        )

    received = parse_sse_data(await asyncio.wait_for(pending_event, timeout=0.2))
    assert received["id"] == created_event.id
    assert received["event_type"] == "session.status"
    await stream.aclose()


def test_sse_encoding_uses_standard_fields() -> None:
    event = {
        "id": 42,
        "event_type": "tool.started",
        "payload": {"name": "computer"},
    }

    encoded = encode_sse_event(event)

    assert encoded.startswith("id: 42\nevent: tool.started\ndata: ")
    assert parse_sse_data(encoded)["payload"] == {"name": "computer"}
    assert encode_heartbeat().startswith("event: heartbeat\ndata: ")


class CollectingSink:
    def __init__(self) -> None:
        self.events: list[tuple[EventType, dict[str, Any]]] = []

    async def emit(self, event_type: EventType, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))


class ToolResultStub:
    output = "完成"
    error = None
    base64_image = "encoded-image"


@pytest.mark.asyncio
async def test_anthropic_callbacks_are_ui_independent_and_ordered() -> None:
    sink = CollectingSink()
    adapter = AnthropicCallbackAdapter(sink)
    await adapter.start()

    adapter.output_callback({"type": "text", "text": "你好"})
    adapter.output_callback({"type": "tool_use", "id": "tool-1", "name": "computer", "input": {}})
    adapter.tool_output_callback(ToolResultStub(), "tool-1")
    await adapter.close()

    assert [event_type for event_type, _ in sink.events] == [
        EventType.ASSISTANT_MESSAGE,
        EventType.TOOL_STARTED,
        EventType.TOOL_RESULT,
        EventType.SCREENSHOT_AVAILABLE,
    ]


class FailingAgentRunner:
    async def run(self, _: str, __: AgentEventSink) -> str:
        raise RuntimeError("模拟 Agent 故障")


@pytest.mark.asyncio
async def test_run_failure_is_persisted_and_session_returns_to_ready(
    api_client: AsyncClient,
    database_factory: async_sessionmaker[AsyncSession],
) -> None:
    created = await create_session(api_client, "失败状态测试")
    session_id = uuid.UUID(str(created["id"]))
    response = await api_client.post(
        f"/api/v1/sessions/{session_id}/runs",
        json={"input": "触发失败"},
    )
    run_id = uuid.UUID(response.json()["id"])
    broker = InMemoryEventBroker()

    await RunExecutor(database_factory, broker, FailingAgentRunner()).execute(run_id)

    async with database_factory() as database_session:
        run = await database_session.get(AgentRun, run_id)
        session = await database_session.get(AgentSession, session_id)
        event_types = list(
            (
                await database_session.scalars(
                    select(SessionEvent.event_type)
                    .where(SessionEvent.run_id == run_id)
                    .order_by(SessionEvent.id)
                )
            ).all()
        )

    assert run is not None and run.status == "FAILED"
    assert run.error == "RuntimeError"
    assert session is not None and session.status == "READY"
    assert event_types == ["run.started", "run.failed"]
