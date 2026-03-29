import hashlib
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import bcrypt
import jwt
from fastapi import Depends, Header, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import ExpiredSignatureError, InvalidTokenError
from pydantic import BaseModel

from csre.core.config import Settings
from csre.core.exceptions import CSREException, ErrorCode

bearer_scheme = HTTPBearer(auto_error=False)


class TokenPayload(BaseModel):
    sub: str
    token_type: str
    jti: str
    exp: int
    iat: int


@dataclass(slots=True)
class EncodedToken:
    token: str
    jti: str
    expires_in: int


def normalize_email(email: str) -> str:
    normalized = unicodedata.normalize("NFKD", email.strip())
    ascii_email = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_email.lower()


def hash_email(email: str) -> str:
    return hashlib.sha256(email.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def create_access_token(subject: str, settings: Settings) -> EncodedToken:
    return _create_token(subject, "access", settings.access_token_ttl_seconds, settings)


def create_refresh_token(subject: str, settings: Settings) -> EncodedToken:
    return _create_token(subject, "refresh", settings.refresh_token_ttl_seconds, settings)


def decode_token(token: str, settings: Settings, *, expected_type: str | None = None) -> TokenPayload:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except ExpiredSignatureError as exc:
        raise CSREException(
            ErrorCode.TOKEN_EXPIRED,
            "Token has expired",
            status.HTTP_401_UNAUTHORIZED,
        ) from exc
    except InvalidTokenError as exc:
        raise CSREException(
            ErrorCode.INVALID_TOKEN,
            "Token is invalid",
            status.HTTP_401_UNAUTHORIZED,
        ) from exc

    token_payload = TokenPayload.model_validate(payload)
    if expected_type and token_payload.token_type != expected_type:
        raise CSREException(
            ErrorCode.INVALID_TOKEN,
            f"Expected a {expected_type} token",
            status.HTTP_401_UNAUTHORIZED,
        )
    return token_payload


async def require_access_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> TokenPayload:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise CSREException(
            ErrorCode.AUTH_REQUIRED,
            "Bearer access token required",
            status.HTTP_401_UNAUTHORIZED,
        )
    return decode_token(credentials.credentials, request.app.state.settings, expected_type="access")


async def require_admin_api_key(
    request: Request,
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> None:
    settings = request.app.state.settings
    if not settings.admin_api_key:
        raise CSREException(
            ErrorCode.ADMIN_FORBIDDEN,
            "Admin API is disabled",
            status.HTTP_403_FORBIDDEN,
        )
    if not x_admin_key or x_admin_key != settings.admin_api_key:
        raise CSREException(
            ErrorCode.ADMIN_FORBIDDEN,
            "Invalid admin key",
            status.HTTP_403_FORBIDDEN,
        )


def _create_token(subject: str, token_type: str, ttl_seconds: int, settings: Settings) -> EncodedToken:
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(seconds=ttl_seconds)
    token_id = str(uuid4())
    token = jwt.encode(
        {
            "sub": subject,
            "token_type": token_type,
            "jti": token_id,
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return EncodedToken(token=token, jti=token_id, expires_in=ttl_seconds)
