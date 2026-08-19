import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AgentSession
from app.domain import SessionStatus
from app.runtime import RuntimeInfo, RuntimeProvider

logger = logging.getLogger(__name__)

ACTIVE_SESSION_STATUSES = {
    SessionStatus.CREATING.value,
    SessionStatus.READY.value,
    SessionStatus.RUNNING.value,
    SessionStatus.STOPPING.value,
}


class RuntimeReconciler:
    """使数据库会话和带标签的 Docker sandbox 最终收敛。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        runtime_provider: RuntimeProvider,
    ) -> None:
        self._session_factory = session_factory
        self._runtime_provider = runtime_provider

    async def reconcile(self) -> None:
        runtimes = await self._runtime_provider.list_managed()
        runtimes_by_session: dict[uuid.UUID, list[RuntimeInfo]] = {}
        for runtime in runtimes:
            runtimes_by_session.setdefault(runtime.session_id, []).append(runtime)

        async with self._session_factory() as database_session:
            sessions = list((await database_session.scalars(select(AgentSession))).all())
            sessions_by_id = {session.id: session for session in sessions}
            now = datetime.now(UTC)

            for runtime in runtimes:
                session = sessions_by_id.get(runtime.session_id)
                if session is None or session.deleted_at is not None:
                    await self._delete_runtime(runtime, "孤儿运行时")

            for session in sessions:
                candidates = runtimes_by_session.get(session.id, [])
                if session.deleted_at is not None:
                    continue

                expires_at = session.expires_at
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
                if expires_at <= now:
                    for runtime in candidates:
                        await self._delete_runtime(runtime, "会话已过期")
                    if session.status != SessionStatus.EXPIRED.value:
                        session.status = SessionStatus.EXPIRED.value
                        session.version += 1
                    continue

                if session.status not in ACTIVE_SESSION_STATUSES:
                    continue

                selected = self._select_runtime(session.runtime_id, candidates)
                for duplicate in candidates:
                    if selected is None or duplicate.runtime_id != selected.runtime_id:
                        await self._delete_runtime(duplicate, "重复运行时")

                if selected is None:
                    if session.status != SessionStatus.CREATING.value:
                        session.status = SessionStatus.FAILED.value
                        session.version += 1
                    continue

                if session.runtime_id != selected.runtime_id:
                    session.runtime_id = selected.runtime_id
                    session.version += 1
                if selected.status == "running":
                    if session.status == SessionStatus.CREATING.value:
                        session.status = SessionStatus.READY.value
                        session.version += 1
                elif session.status == SessionStatus.STOPPING.value:
                    session.status = SessionStatus.STOPPED.value
                    session.version += 1
                else:
                    session.status = SessionStatus.FAILED.value
                    session.version += 1

            await database_session.commit()

    async def run_periodically(self, stop_event: asyncio.Event, interval_seconds: float) -> None:
        while not stop_event.is_set():
            try:
                await self.reconcile()
            except Exception:
                logger.exception("运行时对账失败，将在下一周期重试。")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            except TimeoutError:
                continue

    async def _delete_runtime(self, runtime: RuntimeInfo, reason: str) -> None:
        try:
            await self._runtime_provider.delete(runtime.runtime_id)
            logger.info(
                "已删除%s。",
                reason,
                extra={"runtime_id": runtime.runtime_id, "session_id": str(runtime.session_id)},
            )
        except Exception:
            logger.exception(
                "删除%s失败。",
                reason,
                extra={"runtime_id": runtime.runtime_id, "session_id": str(runtime.session_id)},
            )

    @staticmethod
    def _select_runtime(
        runtime_id: str | None,
        candidates: list[RuntimeInfo],
    ) -> RuntimeInfo | None:
        if runtime_id:
            exact = next((item for item in candidates if item.runtime_id == runtime_id), None)
            if exact is not None:
                return exact
        return candidates[0] if candidates else None
