import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import install_exception_handlers
from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import close_database, get_session_factory
from app.events import close_event_broker
from app.runtime import close_runtime_provider, get_runtime_provider
from app.services.runtime_reconciler import RuntimeReconciler


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """管理应用级资源。"""
    configure_logging()
    settings = get_settings()
    stop_event = asyncio.Event()
    reconciler_task: asyncio.Task[None] | None = None
    if settings.runtime_provider == "docker":
        reconciler = RuntimeReconciler(get_session_factory(), get_runtime_provider())
        await reconciler.reconcile()
        reconciler_task = asyncio.create_task(
            reconciler.run_periodically(
                stop_event,
                settings.runtime_reconcile_interval_seconds,
            ),
            name="runtime-reconciler",
        )
    try:
        yield
    finally:
        stop_event.set()
        if reconciler_task is not None:
            await asyncio.gather(reconciler_task, return_exceptions=True)
        await close_runtime_provider()
        await close_event_broker()
        await close_database()


def create_app() -> FastAPI:
    """创建 FastAPI 应用，便于测试时获得隔离实例。"""
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="可扩展的 Computer Use Agent 会话控制面。",
        lifespan=lifespan,
    )
    install_exception_handlers(application)
    application.include_router(api_router)
    return application


app = create_app()
