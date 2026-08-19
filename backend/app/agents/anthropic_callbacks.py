import asyncio
from collections.abc import Mapping
from typing import Any

from app.agents.base import AgentEventSink
from app.domain import EventType


class CallbackBufferFullError(RuntimeError):
    """回调生产速度超过事件持久化速度。"""


class AnthropicCallbackAdapter:
    """把上游同步回调转换为与 UI 无关的顺序异步事件。"""

    _STOP = object()

    def __init__(self, event_sink: AgentEventSink, *, queue_size: int = 256) -> None:
        self._event_sink = event_sink
        self._queue: asyncio.Queue[tuple[EventType, dict[str, Any]] | object] = asyncio.Queue(
            maxsize=queue_size
        )
        self._worker: asyncio.Task[None] | None = None
        self.api_error: Exception | None = None

    async def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._drain(), name="anthropic-event-adapter")

    async def close(self) -> None:
        if self._worker is None:
            return
        self._put(self._STOP)
        await self._worker
        self._worker = None

    def output_callback(self, block: Any) -> None:
        payload = self._to_mapping(block)
        block_type = payload.get("type")
        if block_type == "text":
            self._put(
                (
                    EventType.ASSISTANT_MESSAGE,
                    {"text": str(payload.get("text", ""))},
                )
            )
        elif block_type == "tool_use":
            self._put(
                (
                    EventType.TOOL_STARTED,
                    {
                        "tool_use_id": payload.get("id"),
                        "name": payload.get("name"),
                        "input": payload.get("input", {}),
                    },
                )
            )

    def tool_output_callback(self, result: Any, tool_use_id: str) -> None:
        error = getattr(result, "error", None)
        output = getattr(result, "output", None)
        self._put(
            (
                EventType.TOOL_RESULT,
                {
                    "tool_use_id": tool_use_id,
                    "is_error": bool(error),
                    "output": str(error or output or "")[:10000],
                },
            )
        )
        if getattr(result, "base64_image", None):
            self._put(
                (
                    EventType.SCREENSHOT_AVAILABLE,
                    {"tool_use_id": tool_use_id},
                )
            )

    def api_response_callback(
        self,
        _: Any,
        response: Any,
        error: Exception | None,
    ) -> None:
        if error is not None:
            self.api_error = error
            return
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int) and status_code >= 400:
            self.api_error = RuntimeError(f"Anthropic API 返回 HTTP {status_code}")

    def _put(self, item: tuple[EventType, dict[str, Any]] | object) -> None:
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull as exc:
            raise CallbackBufferFullError("Agent 回调事件缓冲区已满。") from exc

    async def _drain(self) -> None:
        while True:
            item = await self._queue.get()
            if item is self._STOP:
                return
            event_type, payload = item  # type: ignore[misc]
            await self._event_sink.emit(event_type, payload)

    @staticmethod
    def _to_mapping(value: Any) -> dict[str, Any]:
        if isinstance(value, Mapping):
            return dict(value)
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump(mode="json")
            if isinstance(dumped, dict):
                return dumped
        return {"type": type(value).__name__}
