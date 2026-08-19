import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRun, AgentSession, ChatMessage


class SessionRepository:
    """会话聚合的数据库访问层。"""

    def __init__(self, database_session: AsyncSession) -> None:
        self.database_session = database_session

    async def get_session(
        self,
        session_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> AgentSession | None:
        statement = select(AgentSession).where(
            AgentSession.id == session_id,
            AgentSession.deleted_at.is_(None),
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.database_session.scalar(statement)

    async def list_sessions(
        self,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[AgentSession], int]:
        where_clause = AgentSession.deleted_at.is_(None)
        items = list(
            (
                await self.database_session.scalars(
                    select(AgentSession)
                    .where(where_clause)
                    .order_by(AgentSession.created_at.desc(), AgentSession.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self.database_session.scalar(
            select(func.count()).select_from(AgentSession).where(where_clause)
        )
        return items, int(total or 0)

    async def get_run_by_idempotency_key(
        self,
        session_id: uuid.UUID,
        idempotency_key: str,
    ) -> AgentRun | None:
        return await self.database_session.scalar(
            select(AgentRun).where(
                AgentRun.session_id == session_id,
                AgentRun.idempotency_key == idempotency_key,
            )
        )

    async def list_runs(self, session_id: uuid.UUID) -> list[AgentRun]:
        return list(
            (
                await self.database_session.scalars(
                    select(AgentRun)
                    .where(AgentRun.session_id == session_id)
                    .order_by(AgentRun.created_at, AgentRun.id)
                )
            ).all()
        )

    async def list_messages(self, session_id: uuid.UUID) -> list[ChatMessage]:
        return list(
            (
                await self.database_session.scalars(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == session_id)
                    .order_by(ChatMessage.sequence)
                )
            ).all()
        )

    async def next_message_sequence(self, session_id: uuid.UUID) -> int:
        current = await self.database_session.scalar(
            select(func.max(ChatMessage.sequence)).where(ChatMessage.session_id == session_id)
        )
        return int(current or 0) + 1
