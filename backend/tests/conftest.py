from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.session import get_db_session
from app.main import create_app
from app.runtime import FakeRuntimeProvider, get_runtime_provider
from app.services.run_executor import get_run_executor


class NoopRunExecutor:
    """让会话 API 测试自主决定何时执行后台任务。"""

    async def execute(self, _: object) -> None:
        return


@pytest.fixture
async def database_factory(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_path = tmp_path / "session-api.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    yield session_factory
    await engine.dispose()


@pytest.fixture
async def api_client(
    database_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    """使用真实 SQLAlchemy 仓储和临时 SQLite 文件验证 API。"""

    async def override_database_session() -> AsyncIterator[AsyncSession]:
        async with database_factory() as database_session:
            yield database_session

    runtime_provider = FakeRuntimeProvider()
    application = create_app()
    application.dependency_overrides[get_db_session] = override_database_session
    application.dependency_overrides[get_runtime_provider] = lambda: runtime_provider
    application.dependency_overrides[get_run_executor] = lambda: NoopRunExecutor()

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    application.dependency_overrides.clear()
