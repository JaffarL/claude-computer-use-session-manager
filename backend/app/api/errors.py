from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.services.errors import ApplicationError


def install_exception_handlers(application: FastAPI) -> None:
    """将可预期的业务错误转换为稳定的 JSON 契约。"""

    @application.exception_handler(ApplicationError)
    async def handle_application_error(
        _: Request,
        exc: ApplicationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )
