"""
Orchestration Test Scenario 1 & 2: Success and Self-Correction.
Spec §9.1:
- Agent success: full lifecycle from QUEUED/PREPARING to SUCCEEDED.
- Self-correction after a failing test: consecutive failures tracked and reset on pass.
"""
import pytest
from backend.app.application.agent import run_agent
from backend.app.application.diff import validate_patch
from backend.app.domain.models import Run, RunOptions, RunStatus, VerificationMode
from backend.test_support.fake_sandbox import FakeSandbox, FakeSandboxProvider
from backend.test_support.scripted_llm import ScriptedLLMProvider
from backend.tests.orchestration.conftest import (
    InMemoryObjectStorage,
    InMemoryRunRepository,
    make_test_workspace,
)

FIXED_CALC = (
    "def add(a, b):\n"
    "    return a + b\n\n"
    "def subtract(a, b):\n"
    "    return a - b\n"
)


@pytest.mark.asyncio
async def test_orchestration_success(
    in_memory_repo: InMemoryRunRepository,
    in_memory_storage: InMemoryObjectStorage,
) -> None:
    """Scenario 1: Happy path agent run resulting in SUCCEEDED with validated patch."""
    sandbox = FakeSandbox()
    run = Run(
        id="run-success-1",
        user_id="user-1",
        task="Fix the bug in calculator.py so tests pass",
        status=RunStatus.PREPARING,
        options=RunOptions(verification=VerificationMode.REQUIRED),
    )
    await in_memory_repo.create(run)
    baseline_sha = await make_test_workspace(sandbox, run, in_memory_storage, in_memory_repo)
    run.baseline_sha = baseline_sha
    await in_memory_repo.update_status(run.id, status=RunStatus.RUNNING, baseline_sha=baseline_sha)

    steps = [
        {
            "thought": "I will inspect calculator.py first.",
            "tool_calls": [{"name": "read_file", "arguments": {"path": "calculator.py"}}],
        },
        {
            "thought": "Now I fix the addition bug in calculator.py.",
            "tool_calls": [{"name": "write_file", "arguments": {"path": "calculator.py", "content": FIXED_CALC}}],
        },
        {
            "thought": "I will run the tests to verify the fix.",
            "tool_calls": [{
                "name": "run_command",
                "arguments": {"command": "python -m pytest test_calculator.py", "purpose": "test"},
            }],
        },
        {
            "thought": "Tests passed! I will finish the task.",
            "tool_calls": [{"name": "finish", "arguments": {"summary": "Fixed add function"}}],
        },
    ]

    llm = ScriptedLLMProvider(steps=steps)
    final_run = await run_agent(
        run_id=run.id,
        repository=in_memory_repo,
        sandbox=sandbox,
        llm_provider=llm,
        storage=in_memory_storage,
    )

    assert final_run.status == RunStatus.SUCCEEDED
    assert final_run.error_reason is None

    # Verify event sequence
    events = await in_memory_repo.list_events(run.id)
    assert len(events) >= 8
    seqs = [e.seq for e in events]
    assert seqs == list(range(1, len(events) + 1)), "Event sequence must be monotonic and gap-free"

    types = [e.type for e in events]
    assert "reasoning" in types
    assert "tool_call" in types
    assert "tool_result" in types
    assert "terminal_output" in types
    assert "status_change" in types

    # Verify patch artifact was stored in S3
    patch_key = f"artifacts/{run.user_id}/{run.id}/patch.diff"
    assert patch_key in in_memory_storage.objects
    patch_bytes = in_memory_storage.objects[patch_key]
    assert b"calculator.py" in patch_bytes
    assert b"+    return a + b" in patch_bytes

    # Isolated patch validation
    baseline_tar = in_memory_storage.objects[f"artifacts/{run.user_id}/{run.id}/baseline_snapshot.tar.gz"]
    provider = FakeSandboxProvider()
    valid = await validate_patch(provider, patch_bytes, baseline_tar)
    assert valid is True


@pytest.mark.asyncio
async def test_orchestration_self_correction(
    in_memory_repo: InMemoryRunRepository,
    in_memory_storage: InMemoryObjectStorage,
) -> None:
    """Scenario 2: Agent observes failing test, self-corrects, passes test, and succeeds."""
    sandbox = FakeSandbox()
    run = Run(
        id="run-self-correct",
        user_id="user-1",
        task="Diagnose and fix failing calculator tests",
        status=RunStatus.PREPARING,
        options=RunOptions(verification=VerificationMode.REQUIRED),
    )
    await in_memory_repo.create(run)
    baseline_sha = await make_test_workspace(sandbox, run, in_memory_storage, in_memory_repo)
    run.baseline_sha = baseline_sha
    await in_memory_repo.update_status(run.id, status=RunStatus.RUNNING, baseline_sha=baseline_sha)

    steps = [
        {
            "thought": "Let's first run the test to see what fails.",
            "tool_calls": [{
                "name": "run_command",
                "arguments": {"command": "python -m pytest test_calculator.py", "purpose": "test"},
            }],
        },
        {
            "thought": "Test failed as expected. Now fixing calculator.py.",
            "tool_calls": [{"name": "write_file", "arguments": {"path": "calculator.py", "content": FIXED_CALC}}],
        },
        {
            "thought": "Re-running test to verify self-correction.",
            "tool_calls": [{
                "name": "run_command",
                "arguments": {"command": "python -m pytest test_calculator.py", "purpose": "test"},
            }],
        },
        {
            "thought": "All tests passed. Calling finish.",
            "tool_calls": [{"name": "finish", "arguments": {"summary": "Self-corrected calculator tests"}}],
        },
    ]

    llm = ScriptedLLMProvider(steps=steps)
    final_run = await run_agent(
        run_id=run.id,
        repository=in_memory_repo,
        sandbox=sandbox,
        llm_provider=llm,
        storage=in_memory_storage,
    )

    assert final_run.status == RunStatus.SUCCEEDED
    assert final_run.error_reason is None

    # Check both test executions in events
    events = await in_memory_repo.list_events(run.id)
    cmd_results = [
        e.payload for e in events
        if e.type == "tool_result" and e.payload.get("name") == "run_command"
    ]
    assert len(cmd_results) == 2
    assert cmd_results[0]["exit_code"] != 0, "First test must have failed"
    assert cmd_results[1]["exit_code"] == 0, "Second test must have passed"
