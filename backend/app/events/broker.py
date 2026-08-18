import asyncio
import json
import uuid
from functools import lru_cache
from typing import Any, Protocol

from redis.asyncio import Redis

from app.core.config import get_settings

EventEnvelope = dict[str, Any]


class EventSubscription(Protocol):
    async def get(self, wait_seconds: float) -> EventEnvelope | None: ...

    async def close(self) -> None: ...


class EventBroker(Protocol):
    async def publish(self, session_id: uuid.UUID, event: EventEnvelope) -> None: ...

    async def subscribe(self, session_id: uuid.UUID) -> EventSubscription: ...

    async def close(self) -> None: ...


def _channel_name(session_id: uuid.UUID) -> str:
    return f"computer-use:session:{session_id}:events"


class RedisEventSubscription:
    def __init__(self, pubsub: Any, channel: str) -> None:
        self._pubsub = pubsub
        self._channel = channel

    async def get(self, wait_seconds: float) -> EventEnvelope | None:
        message = await self._pubsub.get_message(
            ignore_subscribe_messages=True,
            timeout=wait_seconds,
        )
        if message is None:
            return None
        data = message.get("data")
        if not isinstance(data, str):
            return None
        parsed = json.loads(data)
        return parsed if isinstance(parsed, dict) else None

    async def close(self) -> None:
        await self._pubsub.unsubscribe(self._channel)
        await self._pubsub.aclose()


class RedisEventBroker:
    """跨 API 进程扇出事件；数据库仍是事件的事实来源。"""

    def __init__(self, redis_url: str) -> None:
        self._redis = Redis.from_url(redis_url, decode_responses=True)

    async def publish(self, session_id: uuid.UUID, event: EventEnvelope) -> None:
        await self._redis.publish(
            _channel_name(session_id),
            json.dumps(event, ensure_ascii=False, separators=(",", ":")),
        )

    async def subscribe(self, session_id: uuid.UUID) -> RedisEventSubscription:
        channel = _channel_name(session_id)
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        return RedisEventSubscription(pubsub, channel)

    async def close(self) -> None:
        await self._redis.aclose()


class InMemoryEventSubscription:
    def __init__(
        self,
        queue: asyncio.Queue[EventEnvelope],
        subscribers: set[asyncio.Queue[EventEnvelope]],
    ) -> None:
        self._queue = queue
        self._subscribers = subscribers

    async def get(self, wait_seconds: float) -> EventEnvelope | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=wait_seconds)
        except TimeoutError:
            return None

    async def close(self) -> None:
        self._subscribers.discard(self._queue)


class InMemoryEventBroker:
    """测试用进程内事件总线。"""

    def __init__(self) -> None:
        self._subscribers: dict[uuid.UUID, set[asyncio.Queue[EventEnvelope]]] = {}

    async def publish(self, session_id: uuid.UUID, event: EventEnvelope) -> None:
        for queue in tuple(self._subscribers.get(session_id, set())):
            await queue.put(event)

    async def subscribe(self, session_id: uuid.UUID) -> InMemoryEventSubscription:
        queue: asyncio.Queue[EventEnvelope] = asyncio.Queue()
        subscribers = self._subscribers.setdefault(session_id, set())
        subscribers.add(queue)
        return InMemoryEventSubscription(queue, subscribers)

    async def close(self) -> None:
        self._subscribers.clear()


@lru_cache
def get_event_broker() -> RedisEventBroker:
    return RedisEventBroker(get_settings().redis_url)


async def close_event_broker() -> None:
    if get_event_broker.cache_info().currsize:
        await get_event_broker().close()
        get_event_broker.cache_clear()
