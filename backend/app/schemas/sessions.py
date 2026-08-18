import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain import MessageRole, RunStatus, SessionStatus


class SessionCreate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    expires_in_seconds: int = Field(default=3600, ge=60, le=86400)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("标题不能只包含空白字符。")
        return normalized


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    status: SessionStatus
    runtime_id: str | None
    version: int
    expires_at: datetime
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    items: list[SessionResponse]
    total: int
    offset: int
    limit: int


class RunCreate(BaseModel):
    input: str = Field(min_length=1, max_length=20000)

    @field_validator("input")
    @classmethod
    def normalize_input(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("任务内容不能只包含空白字符。")
        return normalized


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    status: RunStatus
    input: str
    idempotency_key: str | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunListResponse(BaseModel):
    items: list[RunResponse]


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    run_id: uuid.UUID | None
    role: MessageRole
    content: dict[str, Any]
    sequence: int
    created_at: datetime


class MessageListResponse(BaseModel):
    items: list[MessageResponse]


class VncAccessResponse(BaseModel):
    url: str
    expires_at: datetime


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
