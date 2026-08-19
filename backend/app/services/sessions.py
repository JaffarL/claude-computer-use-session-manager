import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRun, AgentSession, ChatMessage
from app.db.session import get_db_session
from app.domain import MessageRole, RunStatus, SessionStatus
from app.repositories import SessionRepository
from app.runtime import RuntimeProvider, get_runtime_provider
from app.services.errors import (
    ResourceNotFoundError,
    RuntimeOperationError,
    StateConflictError,
)


class SessionService:
    """协调会话状态、持久化和运行时操作。"""

    def __init__(
        self,
        database_session: AsyncSession,
        runtime_provider: RuntimeProvider,
    ) -> None:
        self._database_session = database_session
        self._runtime_provider = runtime_provider
        self._repository = SessionRepository(database_session)

    async def create_session(
        self,
        *,
        title: str | None,
        expires_in_seconds: int,
    ) -> AgentSession:
        session = AgentSession(
            id=uuid.uuid4(),
            title=title,
            status=SessionStatus.CREATING.value,
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in_seconds),
        )
        self._database_session.add(session)
        await self._database_session.commit()

        try:
            handle = await self._runtime_provider.create(session.id)
        except Exception as exc:
            session.status = SessionStatus.FAILED.value
            session.version += 1
            await self._database_session.commit()
            raise RuntimeOperationError("创建会话运行时失败。") from exc

        session.runtime_id = handle.runtime_id
        session.status = SessionStatus.READY.value
        session.version += 1
        await self._database_session.commit()
        await self._database_session.refresh(session)
        return session

    async def get_session(self, session_id: uuid.UUID) -> AgentSession:
        session = await self._repository.get_session(session_id)
        if session is None:
            raise ResourceNotFoundError("会话不存在。")
        return session

    async def list_sessions(
        self,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[AgentSession], int]:
        return await self._repository.list_sessions(offset=offset, limit=limit)

    async def create_run(
        self,
        session_id: uuid.UUID,
        *,
        user_input: str,
        idempotency_key: str | None,
    ) -> tuple[AgentRun, bool]:
        async with self._database_session.begin():
            session = await self._repository.get_session(session_id, for_update=True)
            if session is None:
                raise ResourceNotFoundError("会话不存在。")

            if idempotency_key:
                existing = await self._repository.get_run_by_idempotency_key(
                    session_id,
                    idempotency_key,
                )
                if existing is not None:
                    return existing, True

            if session.status != SessionStatus.READY.value:
                raise StateConflictError(
                    f"会话当前状态为 {session.status}，只有 READY 状态可以提交任务。"
                )

            run = AgentRun(
                id=uuid.uuid4(),
                session_id=session_id,
                status=RunStatus.PENDING.value,
                input=user_input,
                idempotency_key=idempotency_key,
            )
            self._database_session.add(run)
            # run_id 是消息外键；显式 flush 保证所有数据库都先插入父记录。
            await self._database_session.flush()
            message = ChatMessage(
                id=uuid.uuid4(),
                session_id=session_id,
                run_id=run.id,
                role=MessageRole.USER.value,
                content={"text": user_input},
                sequence=await self._repository.next_message_sequence(session_id),
            )
            self._database_session.add(message)
            session.status = SessionStatus.RUNNING.value
            session.version += 1

        await self._database_session.refresh(run)
        return run, False

    async def list_runs(self, session_id: uuid.UUID) -> list[AgentRun]:
        await self.get_session(session_id)
        return await self._repository.list_runs(session_id)

    async def list_messages(self, session_id: uuid.UUID) -> list[ChatMessage]:
        await self.get_session(session_id)
        return await self._repository.list_messages(session_id)

    async def stop_session(self, session_id: uuid.UUID) -> AgentSession:
        session = await self.get_session(session_id)
        if session.status == SessionStatus.STOPPED.value:
            return session
        if session.status == SessionStatus.CREATING.value:
            raise StateConflictError("会话仍在创建，暂时无法停止。")

        session.status = SessionStatus.STOPPING.value
        session.version += 1
        await self._database_session.commit()

        try:
            if session.runtime_id:
                await self._runtime_provider.stop(session.runtime_id)
        except Exception as exc:
            session.status = SessionStatus.FAILED.value
            session.version += 1
            await self._database_session.commit()
            raise RuntimeOperationError("停止会话运行时失败。") from exc

        now = datetime.now(UTC)
        await self._database_session.execute(
            update(AgentRun)
            .where(
                AgentRun.session_id == session_id,
                AgentRun.status.in_([RunStatus.PENDING.value, RunStatus.RUNNING.value]),
            )
            .values(status=RunStatus.CANCELLED.value, finished_at=now)
        )
        session.status = SessionStatus.STOPPED.value
        session.version += 1
        await self._database_session.commit()
        await self._database_session.refresh(session)
        return session

    async def delete_session(self, session_id: uuid.UUID) -> None:
        session = await self.get_session(session_id)
        try:
            if session.runtime_id:
                await self._runtime_provider.delete(session.runtime_id)
        except Exception as exc:
            raise RuntimeOperationError("销毁会话运行时失败。") from exc

        now = datetime.now(UTC)
        await self._database_session.execute(
            update(AgentRun)
            .where(
                AgentRun.session_id == session_id,
                AgentRun.status.in_([RunStatus.PENDING.value, RunStatus.RUNNING.value]),
            )
            .values(status=RunStatus.CANCELLED.value, finished_at=now)
        )
        session.status = SessionStatus.STOPPED.value
        session.deleted_at = now
        session.version += 1
        await self._database_session.commit()


def get_session_service(
    database_session: Annotated[AsyncSession, Depends(get_db_session)],
    runtime_provider: Annotated[RuntimeProvider, Depends(get_runtime_provider)],
) -> SessionService:
    return SessionService(database_session, runtime_provider)
