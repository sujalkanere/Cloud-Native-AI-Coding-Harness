"""
Orchestration Test Scenario 7: Terminate Lifecycle & Container Destruction Timing.
Spec §4, §9.1:
- Terminate: cancels in-flight command, extracts patch against baseline SHA if changes exist,
  destroys container within 5 seconds after patch extraction, transitions to TERMINATED.
"""
from __future__ import annotations

import asyncio

import pytest
from backend.app.application.agent import AgentControl, AgentRunner
from backend.app.domain.models import Run, RunOptions, RunStatus, VerificationMode
from backend.test_support.fake_sandbox import FakeSandbox
from backend.test_support.scripted_llm import ScriptedLLMProvider
from backend.tests.orchestration.conftest import (
    InMemoryObjectStorage,
    InMemoryRunRepository,
    make_test_workspace,
)

MODIFIED_CALC = (
    "def add(a, b):\n"
    "    return a + b\n\n"
    "def subtract(a, b):\n"
    "    return a - b\n"
)


@pytest.mark.asyncio
async def test_terminate_patch_extraction_and_timing(
    in_memory_repo: InMemoryRunRepository,
    in_memory_storage: InMemoryObjectStorage,
) -> None:
    """Scenario 7: Terminate extracts patch before destruction, destroys container within 5s."""
    sandbox = FakeSandbox()
    run = Run(
        id="run-terminate",
        user_id="user-1",
        task="Test terminate lifecycle",
        status=RunStatus.PREPARING,
        options=RunOptions(verification=VerificationMode.REQUIRED),
    )
    await in_memory_repo.create(run)
    baseline_sha = await make_test_workspace(sandbox, run, in_memory_storage, in_memory_repo)
    run.baseline_sha = baseline_sha
    await in_memory_repo.update_status(run.id, status=RunStatus.RUNNING, baseline_sha=baseline_sha)

    control = AgentControl(run_id=run.id, repository=in_memory_repo)

    steps = [
        {
            "thought": "Step 1: Writing modified code.",
            "tool_calls": [
                {"name": "write_file", "arguments": {"path": "calculator.py", "content": MODIFIED_CALC}},
            ],
        },
        {
            "thought": "Step 2: Running a long task.",
            "tool_calls": [{
                "name": "run_command",
                "arguments": {"command": "ping 127.0.0.1 -n 15 > nul", "purpose": "other"},
            }],
        },
    ]

    llm = ScriptedLLMProvider(steps=steps)
    runner = AgentRunner(
        run=run,
        repository=in_memory_repo,
        sandbox=sandbox,
        llm_provider=llm,
        storage=in_memory_storage,
        control=control,
    )
    task = asyncio.create_task(runner.run_loop())

    # Wait for step 1 to write file and step 2 command to launch
    await asyncio.sleep(0.3)

    # Request terminate
    action = await control.request_terminate(sandbox=sandbox, reason="user_cancelled")
    assert action.action == "terminated"

    final_run = await task
    assert final_run.status == RunStatus.TERMINATED
    assert final_run.error_reason == "user_cancelled"

    # Assert patch was extracted and stored in S3 BEFORE container destruction
    patch_key = f"artifacts/{run.user_id}/{run.id}/patch.diff"
    assert patch_key in in_memory_storage.objects
    patch_bytes = in_memory_storage.objects[patch_key]
    assert b"calculator.py" in patch_bytes

    # Assert container destruction timing: within 5.0 seconds after patch extraction
    assert runner.patch_extracted_at is not None
    assert runner.container_destroyed_at is not None
    elapsed = runner.container_destroyed_at - runner.patch_extracted_at
    assert 0 <= elapsed <= 5.0, f"Container destruction took {elapsed}s, must be <= 5.0s"
