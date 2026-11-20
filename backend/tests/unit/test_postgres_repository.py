"""
Unit tests for PostgresRunRepository using in-memory SQLite (aiosqlite).
Adheres strictly to Spec §3.2, §3.3, §3.5, §4, §7.
Validates:
- Monotonic gap-free event sequence numbers under concurrent producers.
- Per-user scoping and cross-user isolation (returns None -> 404).
- Run status transitions and is_pausing flag updates.
- Stale run restart recovery.
"""
from __future__ import annotations

import asyncio

import pytest
from backend.app.domain.interfaces import IRunRepository
from backend.app.domain.models import Run, RunOptions, RunStatus
from backend.app.infrastructure.database.models import Base
from backend.app.infrastructure.database.repository import PostgresRunRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def repo():
    # Use SQLite async for lightning-fast unit tests
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    repository = PostgresRunRepository(session_factory=session_factory)
    yield repository
    await engine.dispose()


def test_protocol_conformance(repo):
    assert isinstance(repo, IRunRepository)


@pytest.mark.asyncio
async def test_run_crud_and_user_isolation(repo):
    # 1. Create run for user_alice
    run_alice = Run(
        id="run_alice_001",
        user_id="user_alice",
        task="Fix calculator bug",
        options=RunOptions(verification="required"),
    )
    created = await repo.create(run_alice)
    assert created.id == "run_alice_001"
    assert created.user_id == "user_alice"
    assert created.status == RunStatus.QUEUED

    # 2. Scoped retrieval: Alice can see her run
    got_alice = await repo.get("run_alice_001", user_id="user_alice")
    assert got_alice is not None
    assert got_alice.id == "run_alice_001"

    # 3. Cross-user isolation: Bob cannot see Alice's run (returns None -> 404)
    got_bob = await repo.get("run_alice_001", user_id="user_bob")
    assert got_bob is None, "Cross-user access must return None to prevent enumeration"

    # 4. List runs scoped to user
    run_bob = Run(
        id="run_bob_001",
        user_id="user_bob",
        task="Write documentation",
    )
    await repo.create(run_bob)

    alice_runs = await repo.list(user_id="user_alice")
    assert len(alice_runs) == 1
    assert alice_runs[0].id == "run_alice_001"

    bob_runs = await repo.list(user_id="user_bob")
    assert len(bob_runs) == 1
    assert bob_runs[0].id == "run_bob_001"


@pytest.mark.asyncio
async def test_update_status_and_is_pausing(repo):
    run = Run(id="run_status_test", user_id="user_1", task="Test status transitions")
    await repo.create(run)

    # Transition to RUNNING
    updated = await repo.update_status("run_status_test", RunStatus.RUNNING)
    assert updated.status == RunStatus.RUNNING
    assert updated.is_pausing is False

    # Set is_pausing
    updated = await repo.update_status(
        "run_status_test",
        RunStatus.RUNNING,
        is_pausing=True,
    )
    assert updated.status == RunStatus.RUNNING
    assert updated.is_pausing is True

    # Transition to FAILED with error reason
    updated = await repo.update_status(
        "run_status_test",
        RunStatus.FAILED,
        error_reason="finish_with_failing_tests",
        is_pausing=False,
    )
    assert updated.status == RunStatus.FAILED
    assert updated.error_reason == "finish_with_failing_tests"
    assert updated.is_pausing is False


@pytest.mark.asyncio
async def test_monotonic_gap_free_sequence_concurrency(repo):
    """
    Stress test verifying that concurrent event producers produce a strictly monotonic,
    gap-free sequence of events (1, 2, 3, ... N) without gaps or collisions.
    Adheres strictly to Spec §3.3 & §9.1.
    """
    run_id = "concurrent_seq_run"
    run = Run(id=run_id, user_id="user_concurrent", task="Concurrent test")
    await repo.create(run)

    num_workers = 10
    events_per_worker = 10
    total_events = num_workers * events_per_worker

    async def _worker(worker_id: int):
        for i in range(events_per_worker):
            await repo.append_event(
                run_id,
                {
                    "type": "terminal_output",
                    "payload": {
                        "worker": worker_id,
                        "index": i,
                        "data": f"Output from worker {worker_id} msg {i}\n",
                    },
                },
            )

    # Launch all workers simultaneously
    tasks = [_worker(w) for w in range(num_workers)]
    await asyncio.gather(*tasks)

    # Fetch all events
    events = await repo.list_events(run_id)
    assert len(events) == total_events

    # Verify gap-free monotonic sequence from 1 to total_events
    seqs = [e.seq for e in events]
    expected_seqs = list(range(1, total_events + 1))
    assert seqs == expected_seqs, "Events must be strictly monotonic and gap-free"

    # Verify after_seq filtering
    filtered_events = await repo.list_events(run_id, after_seq=50)
    assert len(filtered_events) == 50
    assert filtered_events[0].seq == 51
    assert filtered_events[-1].seq == 100


@pytest.mark.asyncio
async def test_recover_stale_runs(repo):
    # Setup runs in various states
    run_running = Run(id="run_stale_1", user_id="u1", task="T1", status=RunStatus.RUNNING)
    run_paused = Run(id="run_stale_2", user_id="u1", task="T2", status=RunStatus.PAUSED, is_pausing=True)
    run_succeeded = Run(id="run_done", user_id="u1", task="T3", status=RunStatus.SUCCEEDED)

    await repo.create(run_running)
    await repo.create(run_paused)
    await repo.create(run_succeeded)

    # Execute recovery
    recovered = await repo.recover_stale_runs()
    recovered_ids = [r.id for r in recovered]

    assert "run_stale_1" in recovered_ids
    assert "run_stale_2" in recovered_ids
    assert "run_done" not in recovered_ids

    # Check database state
    r1 = await repo.get("run_stale_1")
    assert r1.status == RunStatus.FAILED
    assert r1.error_reason == "backend_restarted"

    r2 = await repo.get("run_stale_2")
    assert r2.status == RunStatus.FAILED
    assert r2.error_reason == "backend_restarted"
    assert r2.is_pausing is False

    # Check status_change events were appended
    events_r1 = await repo.list_events("run_stale_1")
    assert any(
        e.type == "status_change" and e.payload.get("error_reason") == "backend_restarted"
        for e in events_r1
    )
