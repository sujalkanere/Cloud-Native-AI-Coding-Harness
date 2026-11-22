"""
Pytest configuration and hermetic in-memory test doubles for Orchestration Tests.
Adheres strictly to Spec §3.4, §4, §9.1.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from backend.app.application.diff import create_baseline
from backend.app.domain.interfaces import IObjectStorage, IRunRepository
from backend.app.domain.models import Run, RunEvent, RunStatus
from backend.test_support.fake_sandbox import FakeSandbox


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

    async def presigned_url(self, key: str, ttl_seconds: int = 3600) -> str:
        return f"https://s3.local/{key}"


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
        """Transitions stale RUNNING/PAUSED runs to FAILED(reason='backend_restarted')."""
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
    """Ensures test environment variables are active for all orchestration tests."""
    monkeypatch.setenv("HARNESS_ENV", "test")
    monkeypatch.setenv("LLM_PROVIDER", "scripted")


@pytest.fixture
def in_memory_repo() -> InMemoryRunRepository:
    return InMemoryRunRepository()


@pytest.fixture
def in_memory_storage() -> InMemoryObjectStorage:
    return InMemoryObjectStorage()


async def make_test_workspace(
    sandbox: FakeSandbox,
    run: Run,
    storage: IObjectStorage,
    repo: IRunRepository | None = None,
) -> str:
    """Helper to initialize workspace with calculator bug and create baseline git commit."""
    await sandbox.start()
    calc_code = (
        "def add(a, b):\n"
        "    return a - b  # Bug!\n\n"
        "def subtract(a, b):\n"
        "    return a - b\n"
    )
    test_code = (
        "from calculator import add, subtract\n\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n\n"
        "def test_subtract():\n"
        "    assert subtract(5, 3) == 2\n"
    )
    await sandbox.write_file("calculator.py", calc_code)
    await sandbox.write_file("test_calculator.py", test_code)
    sha = await create_baseline(sandbox, run, storage, repo)
    return sha
