"""
Unit tests for FastAPI Lifespan, Startup Migrations, and Restart Recovery.

Adheres strictly to Spec §3.4, §3.5, §5, §7:
- Auto-runs Alembic migrations on startup.
- Performs restart recovery: stale runs in RUNNING/PAUSED transition to FAILED(reason='backend_restarted').
- Reaps orphan containers labeled harness.managed=true.
- Initializes sandbox provider warm pool up to warm_pool_size.
- Clean shutdown drains warm pool.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from backend.app.api.main import create_app
from backend.app.application.concurrency import RunConcurrencyManager
from backend.app.application.redaction import SecretRedactor
from backend.app.bootstrap import AppContainer
from backend.app.config import Settings
from backend.app.domain.models import Run, RunStatus
from backend.app.infrastructure.auth.dev import DevAuthProvider
from backend.test_support.fake_sandbox import FakeSandboxProvider
from backend.test_support.scripted_llm import ScriptedLLMProvider
from fastapi.testclient import TestClient

from tests.conftest import InMemoryObjectStorage, InMemoryRunRepository


@pytest.mark.asyncio
async def test_lifespan_startup_recovery_and_warm_pool():
    """
    Asserts that application lifespan:
    1. Executes restart recovery transitioning stale RUNNING runs to FAILED(reason='backend_restarted').
    2. Initializes sandbox provider warm pool.
    3. Calls close() on sandbox provider on shutdown.
    """
    repo = InMemoryRunRepository()
    storage = InMemoryObjectStorage()
    sandbox_provider = FakeSandboxProvider()
    sandbox_provider.initialize = AsyncMock()  # type: ignore
    sandbox_provider.close = AsyncMock()  # type: ignore

    settings = Settings(
        HARNESS_ENV="test",
        LLM_PROVIDER="scripted",
    )

    # Insert a stale RUNNING run and a stale PAUSED run
    run1 = Run(id="run_stale_1", user_id="user_dev", task="stale 1", status=RunStatus.RUNNING)
    run2 = Run(id="run_stale_2", user_id="user_dev", task="stale 2", status=RunStatus.PAUSED)
    await repo.create(run1)
    await repo.create(run2)

    concurrency_mgr = RunConcurrencyManager(
        repository=repo,
        sandbox_provider=sandbox_provider,
        llm_provider=ScriptedLLMProvider(),
        storage=storage,
        settings=settings,
    )

    container = AppContainer(
        settings=settings,
        redactor=SecretRedactor(secrets=[]),
        auth_provider=DevAuthProvider(),
        llm_provider=ScriptedLLMProvider(),
        storage=storage,
        run_repository=repo,
        sandbox_provider=sandbox_provider,
        session_factory=None,  # type: ignore
        concurrency_manager=concurrency_mgr,
    )

    app = create_app(settings=settings, container=container, skip_migrations=True)

    # Entering TestClient context triggers startup lifespan; exiting triggers shutdown
    with TestClient(app) as client:
        # Check liveness during active lifespan
        resp = client.get("/healthz")
        assert resp.status_code == 200

        # Assert stale runs were recovered to FAILED(reason='backend_restarted')
        r1 = await repo.get("run_stale_1")
        assert r1.status == RunStatus.FAILED
        assert r1.error_reason == "backend_restarted"

        r2 = await repo.get("run_stale_2")
        assert r2.status == RunStatus.FAILED
        assert r2.error_reason == "backend_restarted"

        # Assert sandbox warm pool initialize was called
        sandbox_provider.initialize.assert_awaited_once()

    # Assert sandbox close was called upon shutdown
    sandbox_provider.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_startup_migrations():
    """Asserts run_migrations is invoked when skip_migrations=False."""
    settings = Settings(HARNESS_ENV="test", LLM_PROVIDER="scripted")
    repo = InMemoryRunRepository()
    storage = InMemoryObjectStorage()
    sandbox_provider = FakeSandboxProvider()

    concurrency_mgr = RunConcurrencyManager(
        repository=repo,
        sandbox_provider=sandbox_provider,
        llm_provider=ScriptedLLMProvider(),
        storage=storage,
        settings=settings,
    )

    container = AppContainer(
        settings=settings,
        redactor=SecretRedactor(secrets=[]),
        auth_provider=DevAuthProvider(),
        llm_provider=ScriptedLLMProvider(),
        storage=storage,
        run_repository=repo,
        sandbox_provider=sandbox_provider,
        session_factory=None,  # type: ignore
        concurrency_manager=concurrency_mgr,
    )

    with patch("backend.app.api.main.run_migrations", new_callable=AsyncMock) as mock_migrations:
        app = create_app(settings=settings, container=container, skip_migrations=False)
        with TestClient(app) as client:
            client.get("/healthz")
            mock_migrations.assert_awaited_once_with(settings.DATABASE_URL)
