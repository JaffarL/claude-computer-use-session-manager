import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Response, status
from fastapi.responses import StreamingResponse

from app.schemas.events import EventListResponse
from app.schemas.sessions import (
    ErrorResponse,
    MessageListResponse,
    MessageResponse,
    RunCreate,
    RunListResponse,
    RunResponse,
    SessionCreate,
    SessionListResponse,
    SessionResponse,
)
from app.services.event_stream import EventStreamService, get_event_stream_service
from app.services.run_executor import RunExecutor, get_run_executor
from app.services.sessions import SessionService, get_session_service

router = APIRouter(prefix="/sessions")

ERROR_RESPONSES = {
    404: {"model": ErrorResponse, "description": "会话不存在"},
    409: {"model": ErrorResponse, "description": "会话状态冲突"},
    503: {"model": ErrorResponse, "description": "运行时暂不可用"},
}


@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={503: ERROR_RESPONSES[503]},
)
async def create_session(
    payload: SessionCreate,
    service: Annotated[SessionService, Depends(get_session_service)],
) -> SessionResponse:
    """创建逻辑会话并分配运行时。"""
    session = await service.create_session(
        title=payload.title,
        expires_in_seconds=payload.expires_in_seconds,
    )
    return SessionResponse.model_validate(session)


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    service: Annotated[SessionService, Depends(get_session_service)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SessionListResponse:
    """按创建时间倒序分页列出未删除会话。"""
    items, total = await service.list_sessions(offset=offset, limit=limit)
    return SessionListResponse(
        items=[SessionResponse.model_validate(item) for item in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def get_session(
    session_id: uuid.UUID,
    service: Annotated[SessionService, Depends(get_session_service)],
) -> SessionResponse:
    """查询单个会话。"""
    return SessionResponse.model_validate(await service.get_session(session_id))


@router.post(
    "/{session_id}/runs",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=ERROR_RESPONSES,
)
async def create_run(
    session_id: uuid.UUID,
    payload: RunCreate,
    response: Response,
    background_tasks: BackgroundTasks,
    service: Annotated[SessionService, Depends(get_session_service)],
    executor: Annotated[RunExecutor, Depends(get_run_executor)],
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ] = None,
) -> RunResponse:
    """提交任务；相同会话和幂等键始终返回同一个 run。"""
    run, replayed = await service.create_run(
        session_id,
        user_input=payload.input,
        idempotency_key=idempotency_key,
    )
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"
    else:
        background_tasks.add_task(executor.execute, run.id)
    return RunResponse.model_validate(run)


@router.get(
    "/{session_id}/runs",
    response_model=RunListResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def list_runs(
    session_id: uuid.UUID,
    service: Annotated[SessionService, Depends(get_session_service)],
) -> RunListResponse:
    """查询会话的运行历史。"""
    runs = await service.list_runs(session_id)
    return RunListResponse(items=[RunResponse.model_validate(item) for item in runs])


@router.get(
    "/{session_id}/messages",
    response_model=MessageListResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def list_messages(
    session_id: uuid.UUID,
    service: Annotated[SessionService, Depends(get_session_service)],
) -> MessageListResponse:
    """按稳定序号查询持久化聊天历史。"""
    messages = await service.list_messages(session_id)
    return MessageListResponse(items=[MessageResponse.model_validate(item) for item in messages])


@router.get(
    "/{session_id}/events/history",
    response_model=EventListResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def list_event_history(
    session_id: uuid.UUID,
    service: Annotated[EventStreamService, Depends(get_event_stream_service)],
    after_id: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 1000,
) -> EventListResponse:
    """查询事件历史，便于调试和非流式客户端恢复。"""
    return EventListResponse(items=await service.history(session_id, after_id, limit=limit))


@router.get(
    "/{session_id}/events",
    response_class=StreamingResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def stream_events(
    session_id: uuid.UUID,
    service: Annotated[EventStreamService, Depends(get_event_stream_service)],
    last_event_id: Annotated[
        int | None,
        Header(alias="Last-Event-ID", ge=0),
    ] = None,
    after_id: Annotated[int | None, Query(ge=0)] = None,
) -> StreamingResponse:
    """实时推送事件；支持 Last-Event-ID 断线补发。"""
    await service.ensure_session_exists(session_id)
    cursor = max(last_event_id or 0, after_id or 0)
    return StreamingResponse(
        service.stream(session_id, cursor),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/{session_id}/stop",
    response_model=SessionResponse,
    responses=ERROR_RESPONSES,
)
async def stop_session(
    session_id: uuid.UUID,
    service: Annotated[SessionService, Depends(get_session_service)],
) -> SessionResponse:
    """幂等停止会话及其活跃任务。"""
    return SessionResponse.model_validate(await service.stop_session(session_id))


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=ERROR_RESPONSES,
)
async def delete_session(
    session_id: uuid.UUID,
    service: Annotated[SessionService, Depends(get_session_service)],
) -> Response:
    """销毁运行时并软删除会话审计记录。"""
    await service.delete_session(session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
