"""
FastAPI Application Entrypoint & Lifespan Management for Cloud-Native AI Coding Harness.

Adheres strictly to Spec §3.1, §3.5, §7:
- Lifespan executes Alembic auto-migrations on startup (alembic upgrade head).
- Performs restart recovery and orphan container reaping (harness.managed=true).
- Initializes sandbox provider warm pool.
- Registers routers, CORS, and typed domain exception handlers.
- Shutdown: drains warm pool, cleans up concurrency manager, disposes engine.
"""
from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

# Ensure package resolution works across all execution environments
backend_dir = Path(__file__).resolve().parents[2]
workspace_dir = backend_dir.parent
for p in (str(backend_dir), str(workspace_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.app.api.middleware import (
    SecretRedactingLoggingFilter,
    register_exception_handlers,
    setup_cors,
)
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.runs import router as runs_router
from backend.app.api.websocket import router as websocket_router
from backend.app.application.recovery import perform_restart_recovery
from backend.app.bootstrap import AppContainer, bootstrap
from backend.app.config import Settings, get_settings
from backend.app.infrastructure.database.migrations import run_migrations
from fastapi import FastAPI

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    container: AppContainer | None = None,
    skip_migrations: bool = False,
) -> FastAPI:
    """
    FastAPI application factory supporting dependency injection for tests.
    """
    active_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # 1. Wire composition root if not already provided
        app_container = container or bootstrap(active_settings)
        app.state.container = app_container

        # 2. Attach secret redaction logging filter
        redaction_filter = SecretRedactingLoggingFilter(app_container.redactor)
        logging.getLogger().addFilter(redaction_filter)
        logging.getLogger("uvicorn.access").addFilter(redaction_filter)

        # 3. Automatically execute Alembic migrations on startup (Spec §7, Feature 49)
        if not skip_migrations:
            try:
                logger.info("Executing startup Alembic migrations...")
                await run_migrations(active_settings.DATABASE_URL)
                logger.info("Startup Alembic migrations completed successfully.")
            except (OSError, RuntimeError, ValueError, KeyError, AttributeError) as exc:
                logger.warning("Startup Alembic migration skipped or failed: %s", exc)

        # 4. Perform restart recovery (stale runs -> FAILED + reap orphan containers)
        try:
            recovered = await perform_restart_recovery(
                repository=app_container.run_repository,
                sandbox_provider=app_container.sandbox_provider,
            )
            if recovered:
                logger.info("Startup recovery processed %d stale runs.", len(recovered))
        except (OSError, RuntimeError, ValueError, KeyError, AttributeError) as exc:
            logger.warning("Startup recovery encountered issue: %s", exc)

        # 5. Initialize sandbox provider warm pool (Spec §5, Feature 41)
        if hasattr(app_container.sandbox_provider, "initialize"):
            try:
                await app_container.sandbox_provider.initialize()
            except (OSError, RuntimeError, ValueError, KeyError, AttributeError) as exc:
                logger.warning("Sandbox provider warm pool initialization: %s", exc)

        yield

        # 6. Shutdown cleanup
        if app_container.concurrency_manager is not None:
            try:
                await app_container.concurrency_manager.shutdown()
            except (OSError, RuntimeError, ValueError, KeyError, AttributeError) as exc:
                logger.warning("Concurrency manager shutdown: %s", exc)

        if hasattr(app_container.sandbox_provider, "close"):
            try:
                await app_container.sandbox_provider.close()
            except (OSError, RuntimeError, ValueError, KeyError, AttributeError) as exc:
                logger.warning("Sandbox provider shutdown close: %s", exc)

        if hasattr(app_container.session_factory, "kw") and "bind" in app_container.session_factory.kw:
            try:
                engine = app_container.session_factory.kw["bind"]
                await engine.dispose()
            except (OSError, RuntimeError, ValueError, KeyError, AttributeError) as exc:
                logger.warning("Database engine dispose: %s", exc)

    app = FastAPI(
        title="Cloud-Native AI Coding Harness",
        description="FastAPI Control Plane for autonomous coding agent sandboxes",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Attach container to state immediately if provided
    if container is not None:
        app.state.container = container

    # Setup CORS middleware
    setup_cors(app, active_settings.CORS_ORIGINS)

    # Register domain exception handlers (404, 409, 401, 400)
    register_exception_handlers(app)

    # Register routers
    app.include_router(health_router)
    app.include_router(runs_router, prefix="/api")
    app.include_router(websocket_router, prefix="/api")

    return app


_lazy_app: FastAPI | None = None


async def _fallback_asgi_app(scope: Any, receive: Any, send: Any) -> None:
    """Lazy ASGI fallback if module imported before environment variables were configured."""
    global _lazy_app
    if _lazy_app is None:
        _lazy_app = create_app()
    await _lazy_app(scope, receive, send)


# Default module-level application instance for uvicorn
try:
    app = create_app()
except (ValueError, RuntimeError, OSError):
    app = _fallback_asgi_app  # type: ignore
