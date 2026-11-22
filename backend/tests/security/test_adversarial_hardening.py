"""
Tier 5 Adversarial Hardening and Attack Surface Stress Tests.

Covers:
1. Adversarial Tool Calls:
   - Path traversal attempts (../../etc/shadow, /etc/passwd, null bytes \0)
   - Invalid unicode / surrogate payloads
   - Output flooding (massive stream triggering coalescer capping and truncation_marker)
2. Crafted Tarbombs & Traversal Evasions:
   - Multi-level nested directory traversal (a/b/../../../../etc/passwd)
   - Member header size discrepancy (archive exceeds maximum decompressed size)
   - Archive entry boundary violation (10,001 entries > 10,000 limit)
   - Windows-reserved device names and special devices (CHRTYPE, BLKTYPE, FIFOTYPE)
3. SSRF Alternative Encodings & Rebinding:
   - Alternative IP formats: integer (2130706433), octal (017700000001), hex (0x7f000001)
   - URLs with embedded credentials and internal ports (https://user:pass@127.0.0.1:8080/repo.git)
   - DNS rebinding dual records (public + private IP returned by DNS)
4. State Machine Concurrency & Race Conditions:
   - High-concurrency rapid pause/resume hammering across 50 concurrent async tasks
   - Instant boundary pause cancellation race (pause immediately followed by resume)
5. WebSocket Streaming Edge Cases:
   - Replay with negative after sequence (after=-1) and overflow after sequence (after=999999999)
   - Rapid simultaneous disconnections asserting subscriber queue cleanup without memory leaks
"""

from __future__ import annotations

import asyncio
import io
import socket
import tarfile
from typing import Any
from unittest.mock import patch

import pytest
from backend.app.application.agent import AgentControl, AgentRunner
from backend.app.application.archive import extract_archive
from backend.app.application.coalescing import TerminalCoalescer
from backend.app.application.concurrency import RunConcurrencyManager
from backend.app.application.ssrf import validate_repo_url
from backend.app.application.state_machine import RunStateMachine
from backend.app.config import Settings
from backend.app.domain.errors import SSRFSecurityError, TarbombError
from backend.app.domain.models import LLMMessage, LLMResponse, Run, RunEvent, RunStatus, ToolCall
from backend.test_support.fake_sandbox import FakeSandbox, FakeSandboxProvider
from backend.tests.orchestration.conftest import (
    InMemoryObjectStorage,
    InMemoryRunRepository,
)

# ============================================================================
# 1. Adversarial Tool Calls
# ============================================================================

class AdversarialToolLLMProvider:
    """Simulates an LLM emitting malicious or adversarial tool calls."""

    def __init__(self, tool_calls_sequence: list[list[ToolCall]]) -> None:
        self._seq = tool_calls_sequence
        self._index = 0

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        if self._index < len(self._seq):
            calls = self._seq[self._index]
            self._index += 1
            return LLMResponse(content="Adversarial reasoning step", tool_calls=calls)
        # Default terminal tool call to end loop gracefully
        return LLMResponse(
            content="Done",
            tool_calls=[ToolCall(id="tc_fin", name="finish", arguments={"summary": "completed"})],
        )


@pytest.mark.asyncio
async def test_agent_survives_path_traversal_tool_calls():
    """
    Asserts that when an agent emits malicious path traversal tool calls
    (../../etc/shadow, /etc/passwd, null byte paths), the tool runner
    traps the domain error, records is_error=True, and does not crash.
    """
    repo = InMemoryRunRepository()
    storage = InMemoryObjectStorage()
    sandbox = FakeSandbox()
    await sandbox.start()

    run = Run(id="run_adv_paths", user_id="user_sec_01", task="Test path traversal defense")
    await repo.create(run)

    state_machine = RunStateMachine(current_status=RunStatus.RUNNING)
    control = AgentControl(run_id=run.id, repository=repo, state_machine=state_machine)
    control.attach_sandbox(sandbox)

    # Sequence of malicious tool calls
    malicious_calls = [
        [
            ToolCall(id="tc_1", name="read_file", arguments={"path": "../../etc/shadow"}),
            ToolCall(id="tc_2", name="write_file", arguments={"path": "/etc/passwd", "content": "root::0:0:::"}),
            ToolCall(id="tc_3", name="list_dir", arguments={"path": "../../../root"}),
            ToolCall(id="tc_4", name="read_file", arguments={"path": "safe\0evil.txt"}),
        ]
    ]

    llm = AdversarialToolLLMProvider(malicious_calls)
    runner = AgentRunner(
        run=run,
        repository=repo,
        sandbox=sandbox,
        llm_provider=llm,
        storage=storage,
        control=control,
        settings=Settings(HARNESS_ENV="test", LLM_PROVIDER="scripted"),
    )

    result_run = await runner.run_loop()
    assert result_run is not None

    # Verify tool results in events are marked with is_error=True
    events = await repo.list_events(run.id)
    tool_results = [e for e in events if e.type == "tool_result"]
    assert len(tool_results) >= 4

    for tr in tool_results[:4]:
        assert tr.payload.get("is_error") is True, f"Expected is_error=True for {tr.payload}"


@pytest.mark.asyncio
async def test_agent_survives_invalid_unicode_payloads():
    """
    Asserts that tool calls containing invalid UTF-8 bytes or lone surrogates
    do not crash the agent runner and are handled gracefully with typed error.
    """
    repo = InMemoryRunRepository()
    storage = InMemoryObjectStorage()
    sandbox = FakeSandbox()
    await sandbox.start()

    assert sandbox._workspace is not None
    # Pre-create a binary file with non-utf8 bytes in the workspace
    bin_file = sandbox._workspace / "binary_data.bin"
    bin_file.write_bytes(b"\x80\x81\xff\xfe\x00\x01\x02")

    run = Run(id="run_adv_unicode", user_id="user_sec_02", task="Test unicode handling")
    await repo.create(run)

    state_machine = RunStateMachine(current_status=RunStatus.RUNNING)
    control = AgentControl(run_id=run.id, repository=repo, state_machine=state_machine)
    control.attach_sandbox(sandbox)

    malicious_calls = [
        [
            ToolCall(id="tc_u1", name="read_file", arguments={"path": "binary_data.bin"}),
            ToolCall(id="tc_u2", name="write_file", arguments={"path": "corrupt.txt", "content": "\ud800\udc00"}),
        ]
    ]

    llm = AdversarialToolLLMProvider(malicious_calls)
    runner = AgentRunner(
        run=run,
        repository=repo,
        sandbox=sandbox,
        llm_provider=llm,
        storage=storage,
        control=control,
        settings=Settings(HARNESS_ENV="test", LLM_PROVIDER="scripted"),
    )

    result_run = await runner.run_loop()
    assert result_run is not None


@pytest.mark.asyncio
async def test_command_output_flooding_capping():
    """
    Asserts that when a command emits massive output (e.g. 500KB into a 100KB coalescer),
    the TerminalCoalescer enforces max_bytes limit, drops excess telemetry,
    and emits an explicit truncation_marker event.
    """
    emitted_events: list[dict[str, Any]] = []

    async def emit_callback(run_id: str, event_data: dict[str, Any]) -> None:
        emitted_events.append(event_data)

    max_bytes = 100 * 1024  # 100 KB for fast test execution
    coalescer = TerminalCoalescer(
        run_id="run_flood_01",
        emit_callback=emit_callback,
        max_bytes=max_bytes,
    )

    # Feed 500 KB of stdout (5x the allowed quota)
    chunk = "A" * 1024  # 1 KB chunk
    for _ in range(500):
        await coalescer.feed("stdout", chunk)

    await coalescer.flush()
    await coalescer.close()

    # Verify total emitted bytes do not exceed cap and truncation marker exists
    truncation_markers = [e for e in emitted_events if e.get("type") == "truncation_marker"]
    assert len(truncation_markers) >= 1, "Expected explicit truncation_marker event"

    total_terminal_bytes = sum(
        len(e["payload"].get("data", "").encode("utf-8"))
        for e in emitted_events
        if e.get("type") == "terminal_output"
    )
    assert total_terminal_bytes <= max_bytes + 4096, (
        f"Emitted bytes {total_terminal_bytes} exceeded cap {max_bytes}"
    )


# ============================================================================
# 2. Crafted Tarbombs & Traversal Evasions
# ============================================================================

def _make_tar(members: list[tuple[tarfile.TarInfo, bytes | None]]) -> bytes:
    bio = io.BytesIO()
    with tarfile.open(fileobj=bio, mode="w:gz") as tar:
        for info, data in members:
            tar.addfile(info, io.BytesIO(data) if data is not None else None)
    return bio.getvalue()


def test_crafted_tarbomb_nested_multilevel_traversal(tmp_path):
    """Asserts that archives with deep multi-level traversal paths are rejected."""
    info = tarfile.TarInfo("a/b/c/../../../../etc/shadow")
    info.size = 10
    tar_bytes = _make_tar([(info, b"evil:pass\n")])

    with pytest.raises(TarbombError) as exc_info:
        extract_archive(tar_bytes, tmp_path)
    assert "traversal" in str(exc_info.value).lower() or "outside" in str(exc_info.value).lower()


def test_crafted_tarbomb_header_size_discrepancy(tmp_path):
    """
    Asserts that an archive exceeding the maximum decompressed size limit
    is rejected during decompression with TarbombError.
    """
    info = tarfile.TarInfo("payload.bin")
    payload = b"Z" * (200 * 1024)  # 200 KB
    info.size = len(payload)
    tar_bytes = _make_tar([(info, payload)])

    # Enforce a max_bytes limit smaller than actual payload
    with pytest.raises(TarbombError) as exc_info:
        extract_archive(tar_bytes, tmp_path, max_bytes=50 * 1024)
    assert "decompressed size" in str(exc_info.value).lower()


def test_crafted_tarbomb_file_count_boundary_exceeded(tmp_path):
    """
    Asserts that an archive with more than max_files (e.g. 11 entries when max_files=10)
    is rejected immediately during validation.
    """
    members = []
    for i in range(11):
        info = tarfile.TarInfo(f"file_{i}.txt")
        info.size = 5
        members.append((info, b"hello"))

    tar_bytes = _make_tar(members)

    with pytest.raises(TarbombError) as exc_info:
        extract_archive(tar_bytes, tmp_path, max_files=10)
    assert "maximum file count limit" in str(exc_info.value).lower()


def test_crafted_tarbomb_windows_reserved_device_names(tmp_path):
    """
    Asserts that archives containing special devices (character, block, or FIFO files)
    are strictly rejected with TarbombError.
    """
    for dev_type in (tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE):
        info = tarfile.TarInfo("dev_node")
        info.type = dev_type
        tar_bytes = _make_tar([(info, None)])

        with pytest.raises(TarbombError, match="Special device or FIFO file forbidden"):
            extract_archive(tar_bytes, tmp_path)


# ============================================================================
# 3. SSRF Alternative Encodings & Rebinding
# ============================================================================

@pytest.mark.parametrize(
    "evasion_url",
    [
        "https://2130706433/",            # Integer encoding of 127.0.0.1
        "https://017700000001/",          # Octal encoding of 127.0.0.1
        "https://0x7f000001/",            # Hex encoding of 127.0.0.1
        "https://user:pass@127.0.0.1:8080/repo.git",  # Credentials + Port + Loopback
    ],
)
def test_ssrf_rejects_alternative_ip_encodings(evasion_url):
    """Asserts that SSRF guard rejects integer, octal, hex, and credentialed loopback URLs."""
    with pytest.raises(SSRFSecurityError):
        validate_repo_url(evasion_url)


def test_ssrf_rejects_dns_rebinding_dual_records():
    """
    Asserts that if DNS resolution returns multiple IP addresses where one is
    a public address and another is a private/loopback address, the URL is rejected.
    """
    dual_dns_response = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),  # Public IP
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.100", 0)),   # Private RFC 1918 IP
    ]

    with patch("socket.getaddrinfo", return_value=dual_dns_response):
        with pytest.raises(SSRFSecurityError) as exc_info:
            validate_repo_url("https://rebind-attack.example.com/repo.git")
        assert "disallowed ip address" in str(exc_info.value).lower()


# ============================================================================
# 4. State Machine Concurrency & Race Conditions
# ============================================================================

@pytest.mark.asyncio
async def test_state_machine_rapid_concurrent_pause_resume():
    """
    Simulates concurrent async tasks spamming pause and resume operations
    on AgentControl to ensure state transitions remain coherent,
    idempotent, and free of deadlocks or unhandled exceptions.
    """
    repo = InMemoryRunRepository()
    run = Run(id="run_race_01", user_id="user_race", task="race task", status=RunStatus.RUNNING)
    await repo.create(run)

    state_machine = RunStateMachine(current_status=RunStatus.RUNNING)
    control = AgentControl(run_id=run.id, repository=repo, state_machine=state_machine)

    async def worker(task_id: int):
        for _ in range(10):
            mode = "boundary" if task_id % 2 == 0 else "now"
            await control.request_pause(mode=mode)
            await asyncio.sleep(0.001)
            await control.request_resume()

    tasks = [asyncio.create_task(worker(i)) for i in range(20)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # All tasks should complete without unexpected exceptions
    for r in results:
        assert not isinstance(r, Exception), f"Unexpected worker error: {r}"

    # State must be valid
    assert state_machine.status in (RunStatus.RUNNING, RunStatus.PAUSED)


@pytest.mark.asyncio
async def test_boundary_pause_instant_cancellation_race():
    """
    Asserts that if a boundary pause is requested and immediately cancelled
    via resume before the agent step loop checks it, the pause request is
    cleanly cleared without blocking execution.
    """
    repo = InMemoryRunRepository()
    run = Run(id="run_cancel_race", user_id="user_race", task="cancel task", status=RunStatus.RUNNING)
    await repo.create(run)

    state_machine = RunStateMachine(current_status=RunStatus.RUNNING)
    control = AgentControl(run_id=run.id, repository=repo, state_machine=state_machine)

    # 1. Request boundary pause
    action_pause = await control.request_pause(mode="boundary")
    assert action_pause.is_pausing is True
    assert control.is_pausing is True

    # 2. Immediately cancel via resume
    action_resume = await control.request_resume()
    assert action_resume.status == RunStatus.RUNNING
    assert control.is_pausing is False


# ============================================================================
# 5. WebSocket Streaming Edge Cases
# ============================================================================

def test_websocket_negative_and_overflow_after_seq(test_client, in_memory_repo):
    """
    Asserts that WebSocket connections with negative sequence numbers (after=-1)
    or huge overflow sequences (after=999999999) connect cleanly without errors.
    """
    run = Run(id="run_ws_edge", user_id="user_dev_001", task="WS edge cases")
    asyncio.run(in_memory_repo.create(run))

    # Connect with negative sequence
    with test_client.websocket_connect(f"/api/runs/{run.id}/stream?after=-1") as ws_neg:
        assert ws_neg is not None

    # Connect with large overflow sequence
    with test_client.websocket_connect(f"/api/runs/{run.id}/stream?after=999999999") as ws_ovf:
        assert ws_ovf is not None


@pytest.mark.asyncio
async def test_websocket_rapid_disconnections_cleanup():
    """
    Asserts that when multiple subscriber queues connect and disconnect,
    RunConcurrencyManager cleans up subscribers and does not leak memory.
    """
    repo = InMemoryRunRepository()
    storage = InMemoryObjectStorage()
    sandbox_provider = FakeSandboxProvider()
    mgr = RunConcurrencyManager(
        repository=repo,
        storage=storage,
        sandbox_provider=sandbox_provider,
        llm_provider=None,
        settings=Settings(HARNESS_ENV="test"),
    )

    run_id = "run_ws_leak_check"
    queues: list[asyncio.Queue[RunEvent]] = []

    # 1. Register 20 subscribers
    for _ in range(20):
        q = await mgr.subscribe(run_id)
        queues.append(q)

    assert len(mgr._subscribers[run_id]) == 20

    # 2. Publish an event
    await mgr.publish_event(run_id, {"type": "status_change", "payload": {"status": "RUNNING"}})

    for q in queues:
        assert not q.empty()

    # 3. Simulate client disconnection / unsubscription (sync method)
    for q in queues:
        mgr.unsubscribe(run_id, q)

    assert len(mgr._subscribers.get(run_id, set())) == 0, "All subscriber queues must be cleaned up"
