class ApplicationError(Exception):
    """可安全返回给 API 客户端的应用错误。"""

    status_code = 500
    code = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ResourceNotFoundError(ApplicationError):
    status_code = 404
    code = "resource_not_found"


class StateConflictError(ApplicationError):
    status_code = 409
    code = "state_conflict"


class RuntimeOperationError(ApplicationError):
    status_code = 503
    code = "runtime_unavailable"
