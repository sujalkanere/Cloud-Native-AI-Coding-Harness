"""
Unit tests for Concurrency Gating, Gap-Free Monotonic Sequencing, and Terminal Coalescing.

Adheres strictly to Spec §3.1, §3.3, §3.5, §3.6:
- Monotonic gap-free event sequence assignment per run (1..N).
- Concurrency slot allocation & FIFO queue draining (MAX_CONCURRENT_RUNS).
- Terminal output coalescing (100ms or 4KB threshold).
- Separate stdout and stderr stream buffers.
- Hard 5MB output cap per run with explicit truncation_marker event.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from backend.app.application.coalescing import TerminalCoalescer
from backend.app.application.concurrency import RunConcurrencyManager
from backend.app.config import Settings
from backend.app.domain.models import Run, RunStatus
from backend.test_support.fake_sandbox import FakeSandboxProvider
from backend.test_support.scripted_llm import ScriptedLLMProvider

from tests.conftest import InMemoryObjectStorage, InMemoryRunRepository


@pytest.mark.asyncio
async def test_monotonic_gap_free_sequencing():
    """
    Asserts that 100 concurrent event append tasks on the same run produce
    strictly monotonic, gap-free sequence numbers from 1 to 100.
    """
    repo = InMemoryRunRepository()
    run = Run(id="run_mono_001", user_id="user_test", task="test task")
    await repo.create(run)

    async def append_worker(i: int) -> None:
        await repo.append_event(
            run.id,
            {"type": "tool_call", "payload": {"call_id": i}},
        )

    tasks = [asyncio.create_task(append_worker(i)) for i in range(100)]
    await asyncio.gather(*tasks)

    events = await repo.list_events(run.id)
    assert len(events) == 100

    seqs = [e.seq for e in events]
    assert seqs == list(range(1, 101)), "Sequences must be strictly gap-free from 1 to 100"


@pytest.mark.asyncio
async def test_concurrency_max_runs_gating():
    """
    Asserts that MAX_CONCURRENT_RUNS (4) is strictly enforced:
    - 6 runs submitted: 4 active, 2 queued.
    - When 1 active run finishes, the first queued run automatically starts.
    """
    repo = InMemoryRunRepository()
    storage = InMemoryObjectStorage()
    sandbox_provider = FakeSandboxProvider()
    llm = ScriptedLLMProvider()
    settings = Settings(
        HARNESS_ENV="test",
        LLM_PROVIDER="scripted",
        MAX_CONCURRENT_RUNS=4,
    )

    unblock_events = {f"run_slot_{i}": asyncio.Event() for i in range(6)}

    async def mock_worker(run_id: str, **kwargs: Any) -> None:
        await unblock_events[run_id].wait()

    mgr = RunConcurrencyManager(
        repository=repo,
        sandbox_provider=sandbox_provider,
        llm_provider=llm,
        storage=storage,
        settings=settings,
        worker_fn=mock_worker,
    )

    runs: list[Run] = []
    for i in range(6):
        r = Run(id=f"run_slot_{i}", user_id="user_test", task=f"task {i}")
        await repo.create(r)
        submitted = await mgr.enqueue_or_start(r)
        runs.append(submitted)

    # First 4 runs must be allocated slots (active count 4), remaining 2 stay QUEUED
    assert mgr.active_count == 4
    assert mgr.queued_count == 2
    assert runs[0].status == RunStatus.PREPARING
    assert runs[1].status == RunStatus.PREPARING
    assert runs[2].status == RunStatus.PREPARING
    assert runs[3].status == RunStatus.PREPARING
    assert runs[4].status == RunStatus.QUEUED
    assert runs[5].status == RunStatus.QUEUED

    # Unblock run_slot_0 to free up an execution slot
    unblock_events["run_slot_0"].set()

    # Give event loop a cycle to process queue drain
    await asyncio.sleep(0.05)

    # Slot was freed and immediately claimed by run_slot_4
    assert mgr.active_count == 4
    assert mgr.queued_count == 1
    run4 = await repo.get("run_slot_4")
    assert run4 is not None
    assert run4.status == RunStatus.PREPARING

    # Clean up background tasks
    for ev in unblock_events.values():
        ev.set()
    await mgr.shutdown()


@pytest.mark.asyncio
async def test_terminal_coalescer_size_threshold():
    """
    Asserts that feeding >= 4096 bytes triggers an immediate flush without waiting 100ms.
    """
    emitted: list[dict[str, Any]] = []

    async def emit_cb(run_id: str, event_data: dict[str, Any]):
        emitted.append(event_data)

    coalescer = TerminalCoalescer(
        run_id="run_coal_001",
        emit_callback=emit_cb,
        max_bytes=5242880,
        flush_interval_ms=500.0,  # Large interval so timer doesn't fire
        flush_size_bytes=4096,
    )

    # Feed 10 chunks of 500 bytes (total 5000 bytes) rapidly
    chunk = "a" * 500
    for _ in range(10):
        await coalescer.feed("stdout", chunk)

    # Buffer should have exceeded 4096 bytes and flushed at least once
    assert len(emitted) >= 1
    assert emitted[0]["type"] == "terminal_output"
    assert emitted[0]["payload"]["stream"] == "stdout"
    assert len(emitted[0]["payload"]["data"]) == 4096

    # Flush remainder
    await coalescer.flush()
    assert len(emitted) == 2
    assert emitted[1]["payload"]["data"] == "a" * (5000 - 4096)

    await coalescer.close()


@pytest.mark.asyncio
async def test_terminal_coalescer_timer_threshold():
    """
    Asserts that a small chunk (< 4KB) flushes after flush_interval_ms (100ms).
    """
    emitted: list[dict[str, Any]] = []

    async def emit_cb(run_id: str, event_data: dict[str, Any]):
        emitted.append(event_data)

    coalescer = TerminalCoalescer(
        run_id="run_coal_002",
        emit_callback=emit_cb,
        max_bytes=5242880,
        flush_interval_ms=100.0,
        flush_size_bytes=4096,
    )

    # Feed 200 bytes (far below 4KB threshold)
    await coalescer.feed("stdout", "hello world terminal!\n")
    assert len(emitted) == 0, "Should not flush immediately when below size threshold"

    # Wait for timer (100ms + margin)
    await asyncio.sleep(0.15)

    assert len(emitted) == 1
    assert emitted[0]["type"] == "terminal_output"
    assert emitted[0]["payload"]["data"] == "hello world terminal!\n"

    await coalescer.close()


@pytest.mark.asyncio
async def test_terminal_coalescer_stream_separation():
    """
    Asserts stdout and stderr streams are buffered and emitted strictly separately.
    """
    emitted: list[dict[str, Any]] = []

    async def emit_cb(run_id: str, event_data: dict[str, Any]):
        emitted.append(event_data)

    coalescer = TerminalCoalescer(
        run_id="run_coal_003",
        emit_callback=emit_cb,
        max_bytes=5242880,
        flush_interval_ms=500.0,
    )

    # Interleave stdout and stderr writes
    await coalescer.feed("stdout", "stdout line 1\n")
    await coalescer.feed("stderr", "stderr error 1\n")
    await coalescer.feed("stdout", "stdout line 2\n")

    # Flush both streams
    await coalescer.flush()

    assert len(emitted) == 2
    # Verify streams are separate and not mixed into a single payload
    stdout_events = [e for e in emitted if e["payload"]["stream"] == "stdout"]
    stderr_events = [e for e in emitted if e["payload"]["stream"] == "stderr"]

    assert len(stdout_events) == 1
    assert stdout_events[0]["payload"]["data"] == "stdout line 1\nstdout line 2\n"

    assert len(stderr_events) == 1
    assert stderr_events[0]["payload"]["data"] == "stderr error 1\n"

    await coalescer.close()


@pytest.mark.asyncio
async def test_terminal_output_5mb_capping_and_truncation_marker():
    """
    Asserts that terminal output is capped at MAX_OUTPUT_BYTES_PER_RUN (5,242,880 bytes / 5MB),
    emits an explicit truncation_marker event once, and discards all subsequent output.
    """
    emitted: list[dict[str, Any]] = []

    async def emit_cb(run_id: str, event_data: dict[str, Any]):
        emitted.append(event_data)

    max_limit = 10000  # Use 10KB in test for speed, testing exact boundary logic
    coalescer = TerminalCoalescer(
        run_id="run_coal_004",
        emit_callback=emit_cb,
        max_bytes=max_limit,
        flush_interval_ms=500.0,
        flush_size_bytes=4096,
    )

    # Feed 15,000 bytes (exceeding 10,000 byte limit)
    chunk = "x" * 5000
    await coalescer.feed("stdout", chunk)  # 5000 bytes
    await coalescer.feed("stdout", chunk)  # 10000 bytes (hits cap)
    await coalescer.feed("stdout", chunk)  # 15000 bytes (should be discarded)
    await coalescer.flush()

    terminal_events = [e for e in emitted if e["type"] == "terminal_output"]
    truncation_events = [e for e in emitted if e["type"] == "truncation_marker"]

    total_terminal_bytes = sum(len(e["payload"]["data"].encode("utf-8")) for e in terminal_events)
    assert total_terminal_bytes == max_limit, f"Expected {max_limit} bytes, got {total_terminal_bytes}"

    assert len(truncation_events) == 1, "Exactly one truncation_marker event must be emitted"
    assert truncation_events[0]["payload"]["limit"] == max_limit
    assert "truncated" in truncation_events[0]["payload"]["message"].lower()

    # Feed even more data
    await coalescer.feed("stdout", "extra discarded output")
    await coalescer.flush()
    # Ensure no additional events were emitted
    assert len([e for e in emitted if e["type"] == "truncation_marker"]) == 1
    assert sum(len(e["payload"]["data"].encode("utf-8")) for e in emitted if e["type"] == "terminal_output") == max_limit

    await coalescer.close()
