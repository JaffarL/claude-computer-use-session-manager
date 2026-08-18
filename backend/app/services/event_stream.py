import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.models import AgentSession
from app.db.session import get_session_factory
from app.events import EventBroker, EventSubscription, get_event_broker
from app.repositories import EventRepository
from app.schemas.events import EventResponse
from app.services.errors import ResourceNotFoundError
from app.services.events import event_to_envelope


def encode_sse_event(event: dict[str, Any]) -> str:
    """按 SSE 规范编码持久化事件。"""
    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event['id']}\nevent: {event['event_type']}\ndata: {data}\n\n"


def encode_heartbeat() -> str:
    data = json.dumps(
        {"timestamp": datetime.now(UTC).isoformat()},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"event: heartbeat\ndata: {data}\n\n"


@dataclass(frozen=True, slots=True)
class _StreamOverflow:
    reason: str = "客户端消费速度过慢，请使用 Last-Event-ID 重连补发。"


class EventStreamService:
    """组合数据库补发与 Redis 实时订阅。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        broker: EventBroker,
        *,
        heartbeat_seconds: float,
        queue_size: int,
    ) -> None:
        self._session_factory = session_factory
        self._broker = broker
        self._heartbeat_seconds = heartbeat_seconds
        self._queue_size = queue_size

    async def ensure_session_exists(self, session_id: uuid.UUID) -> None:
        async with self._session_factory() as database_session:
            exists = await database_session.scalar(
                select(AgentSession.id).where(
                    AgentSession.id == session_id,
                    AgentSession.deleted_at.is_(None),
                )
            )
        if exists is None:
            raise ResourceNotFoundError("会话不存在。")

    async def history(
        self,
        session_id: uuid.UUID,
        after_id: int,
        *,
        limit: int = 1000,
    ) -> list[EventResponse]:
        await self.ensure_session_exists(session_id)
        async with self._session_factory() as database_session:
            events = await EventRepository(database_session).list_after(
                session_id,
                after_id,
                limit=limit,
            )
            return [EventResponse.model_validate(event) for event in events]

    async def stream(
        self,
        session_id: uuid.UUID,
        after_id: int,
    ) -> AsyncIterator[str]:
        """订阅优先于补发，实时消息按 ID 去重。"""
        subscription = await self._broker.subscribe(session_id)
        live_queue: asyncio.Queue[dict[str, Any] | _StreamOverflow] = asyncio.Queue(
            maxsize=self._queue_size
        )
        producer: asyncio.Task[None] | None = None
        last_sent_id = after_id

        try:
            yield "retry: 2000\n\n"
            async with self._session_factory() as database_session:
                repository = EventRepository(database_session)
                while True:
                    events = await repository.list_after(
                        session_id,
                        last_sent_id,
                        limit=1000,
                    )
                    if not events:
                        break
                    for event in events:
                        envelope = event_to_envelope(event)
                        last_sent_id = event.id
                        yield encode_sse_event(envelope)
                    if len(events) < 1000:
                        break

            producer = asyncio.create_task(
                self._pump_subscription(subscription, live_queue),
                name=f"sse-pump-{session_id}",
            )
            while True:
                try:
                    item = await asyncio.wait_for(
                        live_queue.get(),
                        timeout=self._heartbeat_seconds,
                    )
                except TimeoutError:
                    yield encode_heartbeat()
                    continue

                if isinstance(item, _StreamOverflow):
                    payload = json.dumps(
                        {"reason": item.reason},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    yield f"event: stream.reset\ndata: {payload}\n\n"
                    return

                event_id = int(item.get("id", 0))
                if event_id <= last_sent_id:
                    continue
                last_sent_id = event_id
                yield encode_sse_event(item)
        finally:
            if producer is not None:
                producer.cancel()
                await asyncio.gather(producer, return_exceptions=True)
            await subscription.close()

    async def _pump_subscription(
        self,
        subscription: EventSubscription,
        queue: asyncio.Queue[dict[str, Any] | _StreamOverflow],
    ) -> None:
        while True:
            event = await subscription.get(wait_seconds=1.0)
            if event is None:
                continue
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(_StreamOverflow())
                return


def get_event_stream_service() -> EventStreamService:
    settings = get_settings()
    return EventStreamService(
        get_session_factory(),
        get_event_broker(),
        heartbeat_seconds=settings.sse_heartbeat_seconds,
        queue_size=settings.sse_queue_size,
    )
