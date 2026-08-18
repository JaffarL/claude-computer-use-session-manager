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


@pytest.fixture
async def api_client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    """使用真实 SQLAlchemy 仓储和临时 SQLite 文件验证 API。"""
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

    async def override_database_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as database_session:
            yield database_session

    runtime_provider = FakeRuntimeProvider()
    application = create_app()
    application.dependency_overrides[get_db_session] = override_database_session
    application.dependency_overrides[get_runtime_provider] = lambda: runtime_provider

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    application.dependency_overrides.clear()
    await engine.dispose()
