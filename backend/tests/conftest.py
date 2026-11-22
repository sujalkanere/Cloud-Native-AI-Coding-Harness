"""
Root Pytest Configuration and Test Doubles for Cloud-Native AI Coding Harness.

Provides hermetic in-memory test doubles:
- InMemoryRunRepository: Monotonic gap-free sequencing, row locks, user scoping.
- InMemoryObjectStorage: S3 in-memory store with deterministic presigned URLs.
- FakeSandboxProvider: Local temporary-directory sandbox without Docker.
- ScriptedLLMProvider: Deterministic scriptable LLM responses.
- JWKSHelper: Local RSA key generation and JWT signing for Clerk testing.
- test_container, test_app, test_client fixtures.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from backend.app.api.main import create_app
from backend.app.application.concurrency import RunConcurrencyManager
from backend.app.application.redaction import SecretRedactor
from backend.app.bootstrap import AppContainer
from backend.app.config import Settings
from backend.app.domain.interfaces import IObjectStorage, IRunRepository
from backend.app.domain.models import Run, RunEvent, RunStatus
from backend.app.infrastructure.auth.clerk import ClerkAuthProvider
from backend.app.infrastructure.auth.dev import DevAuthProvider
from backend.test_support.fake_sandbox import FakeSandboxProvider
from backend.test_support.jwks_helper import JWKSHelper
from backend.test_support.scripted_llm import ScriptedLLMProvider
from fastapi import FastAPI
from fastapi.testclient import TestClient


class InMemoryObjectStorage(IObjectStorage):
    """In-memory implementation of IObjectStorage for hermetic tests."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.objects[key] = data

    async def get(self, key: str) -> bytes:
        if key not in self.objects:
            raise FileNotFoundError(f"Storage key '{key}' not found")
        return self.objects[key]

    def presigned_url(self, key: str, ttl: int = 3600) -> str:
        return f"https://s3.local/{key}"

    async def ensure_bucket_exists(self) -> None:
        pass


class InMemoryRunRepository(IRunRepository):
    """In-memory implementation of IRunRepository with monotonic gap-free sequencing."""

    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._events: dict[str, list[RunEvent]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def _get_lock(self, run_id: str) -> asyncio.Lock:
        async with self._global_lock:
            if run_id not in self._locks:
                self._locks[run_id] = asyncio.Lock()
            return self._locks[run_id]

    async def create(self, run: Run) -> Run:
        self._runs[run.id] = run.model_copy(deep=True)
        if run.id not in self._events:
            self._events[run.id] = []
        return self._runs[run.id].model_copy(deep=True)

    async def get(self, run_id: str, user_id: str | None = None) -> Run | None:
        run = self._runs.get(run_id)
        if run is None:
            return None
        if user_id is not None and run.user_id != user_id:
            return None
        return run.model_copy(deep=True)

    async def list(self, user_id: str | None = None) -> list[Run]:
        runs = list(self._runs.values())
        if user_id is not None:
            runs = [r for r in runs if r.user_id == user_id]
        return [r.model_copy(deep=True) for r in runs]

    async def update_status(
        self,
        run_id: str,
        status: RunStatus,
        error_reason: str | None = None,
        is_pausing: bool | None = None,
        baseline_sha: str | None = None,
    ) -> Run:
        lock = await self._get_lock(run_id)
        async with lock:
            run = self._runs.get(run_id)
            if run is None:
                raise ValueError(f"Run '{run_id}' not found")

            run.status = status
            if error_reason is not None:
                run.error_reason = error_reason
            if is_pausing is not None:
                run.is_pausing = is_pausing
            if baseline_sha is not None:
                run.baseline_sha = baseline_sha
            run.updated_at = datetime.now(UTC)
            return run.model_copy(deep=True)

    async def append_event(self, run_id: str, event_data: dict[str, Any]) -> RunEvent:
        lock = await self._get_lock(run_id)
        async with lock:
            events = self._events.setdefault(run_id, [])
            seq = len(events) + 1
            event = RunEvent(
                seq=seq,
                ts=datetime.now(UTC),
                type=event_data.get("type", "unknown"),
                payload=event_data.get("payload", {}),
            )
            events.append(event)
            return event.model_copy(deep=True)

    async def list_events(self, run_id: str, after_seq: int | None = None) -> list[RunEvent]:
        lock = await self._get_lock(run_id)
        async with lock:
            events = self._events.get(run_id, [])
            if after_seq is not None:
                events = [e for e in events if e.seq > after_seq]
            return [e.model_copy(deep=True) for e in events]

    async def recover_stale_runs(self) -> list[Run]:
        recovered: list[Run] = []
        for run_id, run in list(self._runs.items()):
            if run.status in (RunStatus.RUNNING, RunStatus.PAUSED):
                run.status = RunStatus.FAILED
                run.error_reason = "backend_restarted"
                run.is_pausing = False
                run.updated_at = datetime.now(UTC)
                await self.append_event(
                    run_id,
                    {
                        "type": "status_change",
                        "payload": {
                            "status": RunStatus.FAILED.value,
                            "error_reason": "backend_restarted",
                            "is_pausing": False,
                        },
                    },
                )
                recovered.append(run.model_copy(deep=True))
        return recovered


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensures test environment variables are active for all tests."""
    monkeypatch.setenv("HARNESS_ENV", "test")
    monkeypatch.setenv("LLM_PROVIDER", "scripted")
    monkeypatch.setenv("AUTH_PROVIDER", "dev")
    monkeypatch.setenv("MAX_CONCURRENT_RUNS", "4")
    monkeypatch.setenv("MAX_OUTPUT_BYTES_PER_RUN", "5242880")
    monkeypatch.setenv("COMMAND_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("MAX_UPLOAD_MB", "50")


@pytest.fixture
def in_memory_repo() -> InMemoryRunRepository:
    return InMemoryRunRepository()


@pytest.fixture
def in_memory_storage() -> InMemoryObjectStorage:
    return InMemoryObjectStorage()


@pytest.fixture
def fake_sandbox_provider() -> FakeSandboxProvider:
    return FakeSandboxProvider()


@pytest.fixture
def scripted_llm() -> ScriptedLLMProvider:
    return ScriptedLLMProvider()


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        HARNESS_ENV="test",
        LLM_PROVIDER="scripted",
        AUTH_PROVIDER="dev",
        MAX_CONCURRENT_RUNS=4,
        MAX_OUTPUT_BYTES_PER_RUN=5242880,
    )


@pytest.fixture
def test_container(
    test_settings: Settings,
    in_memory_repo: InMemoryRunRepository,
    in_memory_storage: InMemoryObjectStorage,
    fake_sandbox_provider: FakeSandboxProvider,
    scripted_llm: ScriptedLLMProvider,
) -> AppContainer:
    redactor = SecretRedactor(secrets=[])
    auth_provider = DevAuthProvider()
    concurrency_manager = RunConcurrencyManager(
        repository=in_memory_repo,
        sandbox_provider=fake_sandbox_provider,
        llm_provider=scripted_llm,
        storage=in_memory_storage,
        settings=test_settings,
    )
    return AppContainer(
        settings=test_settings,
        redactor=redactor,
        auth_provider=auth_provider,
        llm_provider=scripted_llm,
        storage=in_memory_storage,
        run_repository=in_memory_repo,
        sandbox_provider=fake_sandbox_provider,
        session_factory=None,  # type: ignore
        concurrency_manager=concurrency_manager,
    )


@pytest.fixture
def test_app(test_container: AppContainer) -> FastAPI:
    return create_app(
        settings=test_container.settings,
        container=test_container,
        skip_migrations=True,
    )


@pytest.fixture
def test_client(test_app: FastAPI) -> TestClient:
    return TestClient(test_app)


@pytest.fixture
def clerk_setup(
    test_settings: Settings,
    in_memory_repo: InMemoryRunRepository,
    in_memory_storage: InMemoryObjectStorage,
    fake_sandbox_provider: FakeSandboxProvider,
    scripted_llm: ScriptedLLMProvider,
):
    """Sets up JWKSHelper and Clerk-authenticated AppContainer for security tests."""
    helper = JWKSHelper(kid="test-clerk-key-1", issuer="https://clerk.test")
    jwks_data = helper.get_jwks()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jwks.json"):
            return httpx.Response(200, json=jwks_data)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    clerk_auth = ClerkAuthProvider(
        jwks_url="https://clerk.test/.well-known/jwks.json",
        issuer="https://clerk.test",
        client=client,
    )

    concurrency_mgr = RunConcurrencyManager(
        repository=in_memory_repo,
        sandbox_provider=fake_sandbox_provider,
        llm_provider=scripted_llm,
        storage=in_memory_storage,
        settings=test_settings,
    )

    container = AppContainer(
        settings=test_settings,
        redactor=SecretRedactor(secrets=[]),
        auth_provider=clerk_auth,
        llm_provider=scripted_llm,
        storage=in_memory_storage,
        run_repository=in_memory_repo,
        sandbox_provider=fake_sandbox_provider,
        session_factory=None,  # type: ignore
        concurrency_manager=concurrency_mgr,
    )

    app = create_app(
        settings=test_settings,
        container=container,
        skip_migrations=True,
    )

    test_client = TestClient(app)
    return helper, container, app, test_client
