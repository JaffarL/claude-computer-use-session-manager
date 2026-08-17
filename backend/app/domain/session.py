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
