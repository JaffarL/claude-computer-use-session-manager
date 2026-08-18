from typing import Any, Protocol

from app.domain import EventType


class AgentEventSink(Protocol):
    async def emit(self, event_type: EventType, payload: dict[str, Any]) -> None: ...


class AgentRunner(Protocol):
    async def run(
        self,
        user_input: str,
        event_sink: AgentEventSink,
        *,
        runtime_id: str | None = None,
    ) -> str: ...
