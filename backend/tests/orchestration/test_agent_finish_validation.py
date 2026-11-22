"""
Orchestration Test Scenario 3: Finish Tool Validation.
Spec §4, §9.1:
- 3a: finish_without_fresh_verification (write_file after passing test)
- 3b: finish_with_failing_tests (no test executed)
- 3c: finish_with_failing_tests (most recent test failed)
- 3d: verification="none" transitions unconditionally to SUCCEEDED
"""
from __future__ import annotations

import pytest
from backend.app.application.agent import run_agent
from backend.app.domain.models import Run, RunOptions, RunStatus, VerificationMode
from backend.test_support.fake_sandbox import FakeSandbox
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
async def test_finish_without_fresh_verification(
    in_memory_repo: InMemoryRunRepository,
    in_memory_storage: InMemoryObjectStorage,
) -> None:
    """Scenario 3a: write_file after passing test causes finish to fail with finish_without_fresh_verification."""
    sandbox = FakeSandbox()
    run = Run(
        id="run-stale-verif",
        user_id="user-1",
        task="Modify calculator",
        status=RunStatus.PREPARING,
        options=RunOptions(verification=VerificationMode.REQUIRED),
    )
    await in_memory_repo.create(run)
    baseline_sha = await make_test_workspace(sandbox, run, in_memory_storage, in_memory_repo)
    run.baseline_sha = baseline_sha
    await in_memory_repo.update_status(run.id, status=RunStatus.RUNNING, baseline_sha=baseline_sha)

    steps = [
        {
            "thought": "Fixing code.",
            "tool_calls": [{"name": "write_file", "arguments": {"path": "calculator.py", "content": FIXED_CALC}}],
        },
        {
            "thought": "Running tests.",
            "tool_calls": [{
                "name": "run_command",
                "arguments": {"command": "python -m pytest test_calculator.py", "purpose": "test"},
            }],
        },
        {
            "thought": "Adding another untested modification.",
            "tool_calls": [{"name": "write_file", "arguments": {"path": "calculator.py", "content": FIXED_CALC + "\n# extra comment\n"}}],
        },
        {
            "thought": "Attempting to finish without re-verifying.",
            "tool_calls": [{"name": "finish", "arguments": {"summary": "Done"}}],
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

    assert final_run.status == RunStatus.FAILED
    assert final_run.error_reason == "finish_without_fresh_verification"

    # Patch must still be extracted and saved
    patch_key = f"artifacts/{run.user_id}/{run.id}/patch.diff"
    assert patch_key in in_memory_storage.objects


@pytest.mark.asyncio
async def test_finish_with_failing_tests_never_run(
    in_memory_repo: InMemoryRunRepository,
    in_memory_storage: InMemoryObjectStorage,
) -> None:
    """Scenario 3b: finish called without running tests fails with finish_with_failing_tests."""
    sandbox = FakeSandbox()
    run = Run(
        id="run-no-tests",
        user_id="user-1",
        task="Modify calculator",
        status=RunStatus.PREPARING,
        options=RunOptions(verification=VerificationMode.REQUIRED),
    )
    await in_memory_repo.create(run)
    baseline_sha = await make_test_workspace(sandbox, run, in_memory_storage, in_memory_repo)
    run.baseline_sha = baseline_sha
    await in_memory_repo.update_status(run.id, status=RunStatus.RUNNING, baseline_sha=baseline_sha)

    steps = [
        {
            "thought": "Writing file without testing.",
            "tool_calls": [{"name": "write_file", "arguments": {"path": "calculator.py", "content": FIXED_CALC}}],
        },
        {
            "thought": "Directly finishing without running any tests.",
            "tool_calls": [{"name": "finish", "arguments": {"summary": "Done"}}],
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

    assert final_run.status == RunStatus.FAILED
    assert final_run.error_reason == "finish_with_failing_tests"
    patch_key = f"artifacts/{run.user_id}/{run.id}/patch.diff"
    assert patch_key in in_memory_storage.objects


@pytest.mark.asyncio
async def test_finish_with_failing_tests_last_failed(
    in_memory_repo: InMemoryRunRepository,
    in_memory_storage: InMemoryObjectStorage,
) -> None:
    """Scenario 3c: finish called while most recent test failed -> finish_with_failing_tests."""
    sandbox = FakeSandbox()
    run = Run(
        id="run-last-failed",
        user_id="user-1",
        task="Modify calculator",
        status=RunStatus.PREPARING,
        options=RunOptions(verification=VerificationMode.REQUIRED),
    )
    await in_memory_repo.create(run)
    baseline_sha = await make_test_workspace(sandbox, run, in_memory_storage, in_memory_repo)
    run.baseline_sha = baseline_sha
    await in_memory_repo.update_status(run.id, status=RunStatus.RUNNING, baseline_sha=baseline_sha)

    steps = [
        {
            "thought": "Running test that fails.",
            "tool_calls": [{
                "name": "run_command",
                "arguments": {"command": "python -m pytest test_calculator.py", "purpose": "test"},
            }],
        },
        {
            "thought": "Finishing despite failing test.",
            "tool_calls": [{"name": "finish", "arguments": {"summary": "Done"}}],
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

    assert final_run.status == RunStatus.FAILED
    assert final_run.error_reason == "finish_with_failing_tests"


@pytest.mark.asyncio
async def test_finish_with_verification_none(
    in_memory_repo: InMemoryRunRepository,
    in_memory_storage: InMemoryObjectStorage,
) -> None:
    """Scenario 3d: verification='none' transitions to SUCCEEDED without running tests."""
    sandbox = FakeSandbox()
    run = Run(
        id="run-verif-none",
        user_id="user-1",
        task="Modify calculator without tests",
        status=RunStatus.PREPARING,
        options=RunOptions(verification=VerificationMode.NONE),
    )
    await in_memory_repo.create(run)
    baseline_sha = await make_test_workspace(sandbox, run, in_memory_storage, in_memory_repo)
    run.baseline_sha = baseline_sha
    await in_memory_repo.update_status(run.id, status=RunStatus.RUNNING, baseline_sha=baseline_sha)

    steps = [
        {
            "thought": "Writing file.",
            "tool_calls": [{"name": "write_file", "arguments": {"path": "calculator.py", "content": FIXED_CALC}}],
        },
        {
            "thought": "Finishing under verification=none.",
            "tool_calls": [{"name": "finish", "arguments": {"summary": "Done without tests"}}],
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
    patch_key = f"artifacts/{run.user_id}/{run.id}/patch.diff"
    assert patch_key in in_memory_storage.objects
