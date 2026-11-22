"""
API Security, Authentication, and Exception Handling Middleware.

Adheres strictly to Spec §3.5, §7, §8:
- DevAuthProvider and ClerkAuthProvider integration.
- Strict Per-User Isolation: returns 404 EntityNotFoundError across all endpoints (never 403).
- Domain error mapping:
    - EntityNotFoundError -> 404 Not Found
    - InvalidStateTransitionError -> 409 Conflict
    - AuthenticationError -> 401 Unauthorized
    - SSRFSecurityError -> 400 Bad Request
    - DomainError -> 400 Bad Request
- CORS configuration from CORS_ORIGINS.
- Secret redaction logging filter.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.app.application.redaction import SecretRedactor
from backend.app.bootstrap import AppContainer
from backend.app.domain.errors import (
    AuthenticationError,
    DomainError,
    EntityNotFoundError,
    InvalidStateTransitionError,
    SSRFSecurityError,
)
from backend.app.domain.models import AuthenticatedUser
from fastapi import Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def get_container(request: Request) -> AppContainer:
    """Retrieves AppContainer attached to application state."""
    return request.app.state.container


async def get_current_user(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> AuthenticatedUser:
    """
    FastAPI dependency authenticating HTTP requests via configured IAuthProvider.
    Supports Bearer header and query param token.
    Raises HTTPException(401) on AuthenticationError.
    """
    try:
        return await container.auth_provider.authenticate(request)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def authenticate_websocket(
    websocket: WebSocket,
    container: AppContainer,
) -> AuthenticatedUser:
    """
    Authenticates WebSocket connection via configured IAuthProvider.
    If authentication fails, closes websocket with application code 4401 and raises.
    """
    try:
        return await container.auth_provider.authenticate(websocket)
    except AuthenticationError as exc:
        try:
            await websocket.close(code=4401, reason=str(exc))
        except (OSError, RuntimeError, WebSocketDisconnect) as close_err:
            logger.debug("Failed closing unauthenticated websocket: %s", close_err)
        raise


def setup_cors(app: Any, cors_origins: str | None) -> None:
    """Configures CORS middleware strictly using origins from settings."""
    if not cors_origins:
        origins = ["*"]
    else:
        origins = [origin.strip() for origin in cors_origins.split(",") if origin.strip()]
        if not origins:
            origins = ["*"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def register_exception_handlers(app: Any) -> None:
    """
    Maps typed domain exceptions to HTTP status codes:
    - EntityNotFoundError -> 404 Not Found (strictly 404, never 403)
    - InvalidStateTransitionError -> 409 Conflict
    - AuthenticationError -> 401 Unauthorized
    - SSRFSecurityError -> 400 Bad Request
    - DomainError -> 400 Bad Request
    """

    @app.exception_handler(EntityNotFoundError)
    async def entity_not_found_handler(request: Request, exc: EntityNotFoundError):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(exc)},
        )

    @app.exception_handler(InvalidStateTransitionError)
    async def invalid_transition_handler(request: Request, exc: InvalidStateTransitionError):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(exc)},
        )

    @app.exception_handler(AuthenticationError)
    async def authentication_error_handler(request: Request, exc: AuthenticationError):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": str(exc)},
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(SSRFSecurityError)
    async def ssrf_error_handler(request: Request, exc: SSRFSecurityError):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(exc)},
        )

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(exc)},
        )


class SecretRedactingLoggingFilter(logging.Filter):
    """Logging filter replacing sensitive tokens and secrets with [REDACTED]."""

    def __init__(self, redactor: SecretRedactor) -> None:
        super().__init__()
        self.redactor = redactor

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.redactor.redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = self.redactor.redact_dict(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    self.redactor.redact(arg) if isinstance(arg, str) else arg
                    for arg in record.args
                )
        return True
