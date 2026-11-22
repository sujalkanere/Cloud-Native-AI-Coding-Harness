"""
Orchestration Test Scenario 8: Baseline SHA Diffing.
Spec §4, §9.1:
- Asserting diff generated against baseline commit SHA even if agent committed changes.
"""
from __future__ import annotations

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
async def test_diff_computed_against_baseline_sha_even_with_agent_git_commits(
    in_memory_repo: InMemoryRunRepository,
    in_memory_storage: InMemoryObjectStorage,
) -> None:
    """Scenario 8: Git diff is computed against baseline commit SHA, not HEAD, capturing agent commits."""
    sandbox = FakeSandbox()
    run = Run(
        id="run-baseline-sha-diff",
        user_id="user-1",
        task="Fix calculator and commit changes",
        status=RunStatus.PREPARING,
        options=RunOptions(verification=VerificationMode.REQUIRED),
    )
    await in_memory_repo.create(run)
    baseline_sha = await make_test_workspace(sandbox, run, in_memory_storage, in_memory_repo)
    run.baseline_sha = baseline_sha
    await in_memory_repo.update_status(run.id, status=RunStatus.RUNNING, baseline_sha=baseline_sha)

    steps = [
        {
            "thought": "Writing fixed code.",
            "tool_calls": [{"name": "write_file", "arguments": {"path": "calculator.py", "content": FIXED_CALC}}],
        },
        {
            "thought": "Agent committing changes inside workspace git repository.",
            "tool_calls": [{
                "name": "run_command",
                "arguments": {"command": "git add -A && git commit -m \"Agent commit in workspace\"", "purpose": "other"},
            }],
        },
        {
            "thought": "Running tests.",
            "tool_calls": [{
                "name": "run_command",
                "arguments": {"command": "python -m pytest test_calculator.py", "purpose": "test"},
            }],
        },
        {
            "thought": "Finishing.",
            "tool_calls": [{"name": "finish", "arguments": {"summary": "Fixed and committed"}}],
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

    # Assert patch is non-empty and stored in S3
    patch_key = f"artifacts/{run.user_id}/{run.id}/patch.diff"
    assert patch_key in in_memory_storage.objects
    patch_bytes = in_memory_storage.objects[patch_key]
    assert b"calculator.py" in patch_bytes
    assert b"+    return a + b" in patch_bytes

    # Assert patch validates cleanly against the clean baseline snapshot
    baseline_tar = in_memory_storage.objects[f"artifacts/{run.user_id}/{run.id}/baseline_snapshot.tar.gz"]
    provider = FakeSandboxProvider()
    valid = await validate_patch(provider, patch_bytes, baseline_tar)
    assert valid is True
