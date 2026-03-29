from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ResponseMeta(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: int | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class Envelope(BaseModel):
    success: bool
    data: Any | None = None
    meta: ResponseMeta = Field(default_factory=ResponseMeta)
    error: ErrorBody | None = None


def success_response(data: Any, *, duration_ms: int | None = None) -> Envelope:
    return Envelope(
        success=True,
        data=data,
        meta=ResponseMeta(duration_ms=duration_ms),
        error=None,
    )


def error_response(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    duration_ms: int | None = None,
) -> Envelope:
    return Envelope(
        success=False,
        data=None,
        meta=ResponseMeta(duration_ms=duration_ms),
        error=ErrorBody(code=code, message=message, details=details or {}),
    )

