import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SessionEvent
from app.domain import EventType
from app.events import EventBroker
from app.repositories import EventRepository
from app.schemas.events import EventResponse

logger = logging.getLogger(__name__)


def event_to_envelope(event: SessionEvent) -> dict[str, Any]:
    return EventResponse.model_validate(event).model_dump(mode="json")


class EventService:
    """先持久化事件，再尽力通过 Redis 实时发布。"""

    def __init__(self, database_session: AsyncSession, broker: EventBroker) -> None:
        self._database_session = database_session
        self._broker = broker
        self._repository = EventRepository(database_session)

    async def append(
        self,
        *,
        session_id: uuid.UUID,
        run_id: uuid.UUID | None,
        event_type: EventType,
        payload: dict[str, Any],
    ) -> SessionEvent:
        event = SessionEvent(
            session_id=session_id,
            run_id=run_id,
            event_type=event_type.value,
            payload=payload,
        )
        self._database_session.add(event)
        await self._database_session.commit()
        await self._database_session.refresh(event)
        envelope = event_to_envelope(event)
        try:
            await self._broker.publish(session_id, envelope)
        except Exception:
            logger.warning(
                "Redis 事件发布失败，客户端可通过数据库补发恢复。",
                exc_info=True,
                extra={"session_id": str(session_id), "event_id": event.id},
            )
        return event

    async def list_after(
        self,
        session_id: uuid.UUID,
        after_id: int,
        *,
        limit: int = 1000,
    ) -> list[SessionEvent]:
        return await self._repository.list_after(session_id, after_id, limit=limit)
