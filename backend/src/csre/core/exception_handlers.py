from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from csre.core.exceptions import CSREException, ErrorCode
from csre.schemas.envelope import error_response


def _envelope_response(status_code: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    envelope = error_response(code=code, message=message, details=details)
    return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(CSREException)
    async def handle_csre_exception(_: Request, exc: CSREException) -> JSONResponse:
        return _envelope_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_exception(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _envelope_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ErrorCode.VALIDATION_ERROR,
            "Request validation failed",
            {"errors": exc.errors()},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _envelope_response(exc.status_code, str(exc.status_code), exc.detail)
