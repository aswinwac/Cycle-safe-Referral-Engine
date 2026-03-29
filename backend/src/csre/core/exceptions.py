from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    AUTH_REQUIRED = "AUTH_REQUIRED"
    CYCLE_DETECTED = "CYCLE_DETECTED"
    EMAIL_EXISTS = "EMAIL_EXISTS"
    SELF_REFERRAL = "SELF_REFERRAL"
    DUPLICATE_REFERRAL = "DUPLICATE_REFERRAL"
    VELOCITY_EXCEEDED = "VELOCITY_EXCEEDED"
    FRAUD_BLOCKED = "FRAUD_BLOCKED"
    INVALID_TOKEN = "INVALID_TOKEN"
    USER_NOT_FOUND = "USER_NOT_FOUND"
    USERNAME_EXISTS = "USERNAME_EXISTS"
    INVALID_CODE = "INVALID_CODE"
    GRAPH_WRITE_FAILED = "GRAPH_WRITE_FAILED"
    LOCK_TIMEOUT = "LOCK_TIMEOUT"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    REFERRAL_NOT_FOUND = "REFERRAL_NOT_FOUND"
    ADMIN_FORBIDDEN = "ADMIN_FORBIDDEN"


class CSREException(Exception):
    def __init__(
        self,
        code: ErrorCode | str,
        message: str,
        status_code: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = message
        self.status_code = status_code
        self.details = details or {}
