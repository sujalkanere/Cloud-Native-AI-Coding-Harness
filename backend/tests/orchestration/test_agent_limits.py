"""
Orchestration Test Scenario 9: Hard Failure Limits.
Spec §4, §9.1:
- 9a: AGENT_MAX_CONSECUTIVE_FAILURES (5) -> FAILED(reason="max_consecutive_failures_exceeded")
- 9b: AGENT_MAX_STEPS (40) -> FAILED(reason="max_steps_exceeded")
- 9c: AGENT_MAX_TOKENS (200000) -> FAILED(reason="max_tokens_exceeded")
"""
from __future__ import annotations

import pytest
from backend.app.application.agent import run_agent
from backend.app.config import Settings
from backend.app.domain.models import Run, RunOptions, RunStatus, VerificationMode
from backend.test_support.fake_sandbox import FakeSandbox
from backend.test_support.scripted_llm import ScriptedLLMProvider
from backend.tests.orchestration.conftest import (
    InMemoryObjectStorage,
    InMemoryRunRepository,
    make_test_workspace,
)


@pytest.mark.asyncio
async def test_max_consecutive_failures(
    in_memory_repo: InMemoryRunRepository,
    in_memory_storage: InMemoryObjectStorage,
) -> None:
    """Scenario 9a: 5 consecutive failing commands transitions to FAILED(max_consecutive_failures_exceeded)."""
    sandbox = FakeSandbox()
    run = Run(
        id="run-consecutive-failures",
        user_id="user-1",
        task="Test consecutive failures limit",
        status=RunStatus.PREPARING,
        options=RunOptions(verification=VerificationMode.REQUIRED),
    )
    await in_memory_repo.create(run)
    baseline_sha = await make_test_workspace(sandbox, run, in_memory_storage, in_memory_repo)
    run.baseline_sha = baseline_sha
    await in_memory_repo.update_status(run.id, status=RunStatus.RUNNING, baseline_sha=baseline_sha)

    # 5 consecutive commands that fail (exit code 1)
    steps = [
        {
            "thought": f"Attempt {i+1} with failing command.",
            "tool_calls": [{
                "name": "run_command",
                "arguments": {"command": "python -c \"import sys; sys.exit(1)\"", "purpose": "other"},
            }],
        }
        for i in range(5)
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
    assert final_run.error_reason == "max_consecutive_failures_exceeded"


@pytest.mark.asyncio
async def test_max_steps_exceeded(
    in_memory_repo: InMemoryRunRepository,
    in_memory_storage: InMemoryObjectStorage,
) -> None:
    """Scenario 9b: Reaching max steps transitions to FAILED(max_steps_exceeded)."""
    sandbox = FakeSandbox()
    run = Run(
        id="run-max-steps",
        user_id="user-1",
        task="Test max steps limit",
        status=RunStatus.PREPARING,
        options=RunOptions(verification=VerificationMode.REQUIRED),
    )
    await in_memory_repo.create(run)
    baseline_sha = await make_test_workspace(sandbox, run, in_memory_storage, in_memory_repo)
    run.baseline_sha = baseline_sha
    await in_memory_repo.update_status(run.id, status=RunStatus.RUNNING, baseline_sha=baseline_sha)

    # Test with custom max steps setting = 3 for fast test execution
    custom_settings = Settings(
        HARNESS_ENV="test",
        LLM_PROVIDER="scripted",
        AGENT_MAX_STEPS=3,
    )

    steps = [
        {
            "thought": f"Step {i+1}",
            "tool_calls": [{"name": "read_file", "arguments": {"path": "calculator.py"}}],
        }
        for i in range(5)
    ]

    llm = ScriptedLLMProvider(steps=steps)
    final_run = await run_agent(
        run_id=run.id,
        repository=in_memory_repo,
        sandbox=sandbox,
        llm_provider=llm,
        storage=in_memory_storage,
        settings=custom_settings,
    )

    assert final_run.status == RunStatus.FAILED
    assert final_run.error_reason == "max_steps_exceeded"


@pytest.mark.asyncio
async def test_max_tokens_exceeded(
    in_memory_repo: InMemoryRunRepository,
    in_memory_storage: InMemoryObjectStorage,
) -> None:
    """Scenario 9c: Total tokens exceeding AGENT_MAX_TOKENS transitions to FAILED(max_tokens_exceeded)."""
    sandbox = FakeSandbox()
    run = Run(
        id="run-max-tokens",
        user_id="user-1",
        task="Test max tokens limit",
        status=RunStatus.PREPARING,
        options=RunOptions(verification=VerificationMode.REQUIRED),
    )
    await in_memory_repo.create(run)
    baseline_sha = await make_test_workspace(sandbox, run, in_memory_storage, in_memory_repo)
    run.baseline_sha = baseline_sha
    await in_memory_repo.update_status(run.id, status=RunStatus.RUNNING, baseline_sha=baseline_sha)

    # Step reporting 250,000 tokens (exceeds default AGENT_MAX_TOKENS = 200,000)
    steps = [
        {
            "thought": "A very large prompt and completion.",
            "total_tokens": 250000,
            "tool_calls": [{"name": "read_file", "arguments": {"path": "calculator.py"}}],
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
    assert final_run.error_reason == "max_tokens_exceeded"
