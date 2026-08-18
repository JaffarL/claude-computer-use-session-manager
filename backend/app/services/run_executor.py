import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents import AgentEventSink, AgentRunner, AnthropicAgentRunner, FakeAgentRunner
from app.core.config import get_settings
from app.db.models import AgentRun, AgentSession, ChatMessage
from app.db.session import get_session_factory
from app.domain import EventType, MessageRole, RunStatus, SessionStatus
from app.events import EventBroker, get_event_broker
from app.repositories import SessionRepository
from app.services.events import EventService


class PersistentEventSink:
    def __init__(
        self,
        event_service: EventService,
        session_id: uuid.UUID,
        run_id: uuid.UUID,
    ) -> None:
        self._event_service = event_service
        self._session_id = session_id
        self._run_id = run_id

    async def emit(self, event_type: EventType, payload: dict[str, object]) -> None:
        await self._event_service.append(
            session_id=self._session_id,
            run_id=self._run_id,
            event_type=event_type,
            payload=payload,
        )


class RunExecutor:
    """使用独立数据库会话执行任务，避免依赖 HTTP 请求生命周期。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        broker: EventBroker,
        agent_runner: AgentRunner,
    ) -> None:
        self._session_factory = session_factory
        self._broker = broker
        self._agent_runner = agent_runner

    async def execute(self, run_id: uuid.UUID) -> None:
        async with self._session_factory() as database_session:
            run = await database_session.scalar(
                select(AgentRun).where(AgentRun.id == run_id).with_for_update()
            )
            if run is None or run.status != RunStatus.PENDING.value:
                return
            session = await database_session.get(AgentSession, run.session_id)
            if session is None or session.deleted_at is not None:
                return

            event_service = EventService(database_session, self._broker)
            event_sink: AgentEventSink = PersistentEventSink(
                event_service,
                run.session_id,
                run.id,
            )
            run.status = RunStatus.RUNNING.value
            run.started_at = datetime.now(UTC)
            session.status = SessionStatus.RUNNING.value
            await event_service.append(
                session_id=run.session_id,
                run_id=run.id,
                event_type=EventType.RUN_STARTED,
                payload={"input": run.input},
            )

            try:
                final_text = await self._agent_runner.run(
                    run.input,
                    event_sink,
                    runtime_id=session.runtime_id,
                )
                await database_session.refresh(run)
                await database_session.refresh(session)
                if run.status == RunStatus.CANCELLED.value:
                    return

                message = ChatMessage(
                    id=uuid.uuid4(),
                    session_id=run.session_id,
                    run_id=run.id,
                    role=MessageRole.ASSISTANT.value,
                    content={"text": final_text},
                    sequence=await SessionRepository(database_session).next_message_sequence(
                        run.session_id
                    ),
                )
                database_session.add(message)
                run.status = RunStatus.COMPLETED.value
                run.finished_at = datetime.now(UTC)
                session.status = SessionStatus.READY.value
                session.version += 1
                await event_service.append(
                    session_id=run.session_id,
                    run_id=run.id,
                    event_type=EventType.ASSISTANT_MESSAGE,
                    payload={"message_id": str(message.id), "text": final_text},
                )
                await event_service.append(
                    session_id=run.session_id,
                    run_id=run.id,
                    event_type=EventType.RUN_COMPLETED,
                    payload={"status": RunStatus.COMPLETED.value},
                )
            except Exception as exc:
                await database_session.rollback()
                run = await database_session.get(AgentRun, run_id)
                if run is None or run.status == RunStatus.CANCELLED.value:
                    return
                session = await database_session.get(AgentSession, run.session_id)
                run.status = RunStatus.FAILED.value
                run.error = type(exc).__name__
                run.finished_at = datetime.now(UTC)
                if session is not None:
                    session.status = SessionStatus.READY.value
                    session.version += 1
                await EventService(database_session, self._broker).append(
                    session_id=run.session_id,
                    run_id=run.id,
                    event_type=EventType.RUN_FAILED,
                    payload={"error": type(exc).__name__},
                )


def get_run_executor() -> RunExecutor:
    settings = get_settings()
    if settings.agent_provider == "anthropic":
        if settings.anthropic_api_key is None:
            raise RuntimeError("AGENT_PROVIDER=anthropic 时必须配置 Anthropic 凭据。")
        if not settings.anthropic_model:
            raise RuntimeError("AGENT_PROVIDER=anthropic 时必须配置 ANTHROPIC_MODEL。")
        agent_runner: AgentRunner = AnthropicAgentRunner(
            api_key=settings.anthropic_api_key.get_secret_value(),
            base_url=settings.anthropic_base_url,
            model=settings.anthropic_model,
            max_tokens=settings.anthropic_max_tokens,
            max_iterations=settings.anthropic_max_iterations,
        )
    else:
        agent_runner = FakeAgentRunner(settings.fake_agent_step_delay_seconds)
    return RunExecutor(
        get_session_factory(),
        get_event_broker(),
        agent_runner,
    )
