import asyncio

from app.agents.base import AgentEventSink
from app.domain import EventType


class FakeAgentRunner:
    """可重复、零 API 成本的事件流执行器。"""

    def __init__(self, step_delay_seconds: float = 0.08) -> None:
        self._step_delay_seconds = step_delay_seconds

    async def run(self, user_input: str, event_sink: AgentEventSink) -> str:
        pieces = ["正在分析任务。", "准备调用浏览器工具。"]
        for index, text in enumerate(pieces, start=1):
            await event_sink.emit(
                EventType.ASSISTANT_DELTA,
                {"index": index, "text": text},
            )
            await asyncio.sleep(self._step_delay_seconds)

        tool_use_id = "fake-browser-001"
        await event_sink.emit(
            EventType.TOOL_STARTED,
            {
                "tool_use_id": tool_use_id,
                "name": "computer",
                "input": {"action": "screenshot"},
            },
        )
        await asyncio.sleep(self._step_delay_seconds)
        await event_sink.emit(
            EventType.TOOL_RESULT,
            {
                "tool_use_id": tool_use_id,
                "is_error": False,
                "output": "fake screenshot captured",
            },
        )
        await event_sink.emit(
            EventType.SCREENSHOT_AVAILABLE,
            {"tool_use_id": tool_use_id, "source": "fake"},
        )

        return f"模拟任务已完成：{user_input}"
