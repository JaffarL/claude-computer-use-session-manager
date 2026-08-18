from enum import StrEnum


class SessionStatus(StrEnum):
    """逻辑会话状态。"""

    CREATING = "CREATING"
    READY = "READY"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class RunStatus(StrEnum):
    """一次用户任务的执行状态。"""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class MessageRole(StrEnum):
    """持久化聊天消息的角色。"""

    USER = "USER"
    ASSISTANT = "ASSISTANT"
    TOOL = "TOOL"
    SYSTEM = "SYSTEM"


class EventType(StrEnum):
    """可持久化并通过 SSE 投递的业务事件。"""

    SESSION_STATUS = "session.status"
    RUN_STARTED = "run.started"
    ASSISTANT_DELTA = "assistant.delta"
    ASSISTANT_MESSAGE = "assistant.message"
    TOOL_STARTED = "tool.started"
    TOOL_RESULT = "tool.result"
    SCREENSHOT_AVAILABLE = "screenshot.available"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
