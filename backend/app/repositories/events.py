import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SessionEvent


class EventRepository:
    """事件日志只追加、按全局单调 ID 查询。"""

    def __init__(self, database_session: AsyncSession) -> None:
        self.database_session = database_session

    async def list_after(
        self,
        session_id: uuid.UUID,
        after_id: int,
        *,
        limit: int = 1000,
    ) -> list[SessionEvent]:
        return list(
            (
                await self.database_session.scalars(
                    select(SessionEvent)
                    .where(
                        SessionEvent.session_id == session_id,
                        SessionEvent.id > after_id,
                    )
                    .order_by(SessionEvent.id)
                    .limit(limit)
                )
            ).all()
        )
