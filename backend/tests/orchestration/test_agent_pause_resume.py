"""
Orchestration Test Scenario 4 & 5: Pause and Resume Controls.
Spec §3.4, §4, §9.1:
- 4a: Boundary pause: sets is_pausing=True, completes current step, halts at boundary.
- 4b: Now pause: halts run immediately and cancels running shell command.
- 4c: In-flight LLM call pause: LLM call finishes and reasoning recorded, halts before tools.
- 5a: Boundary pause cancellation: resume called while is_pausing=True clears flag and stays RUNNING.
- 5b: Resume from PAUSED: transitions to RUNNING and completes execution.
"""
from __future__ import annotations

import asyncio

import pytest
from backend.app.application.agent import AgentControl, run_agent
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
async def test_pause_boundary_mode(
    in_memory_repo: InMemoryRunRepository,
    in_memory_storage: InMemoryObjectStorage,
) -> None:
    """Scenario 4a: Boundary pause completes in-flight step then halts in PAUSED."""
    sandbox = FakeSandbox()
    run = Run(
        id="run-pause-boundary",
        user_id="user-1",
        task="Test boundary pause",
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
            "thought": "Step 1: Reading file with small delay.",
            "delay": 0.2,
            "tool_calls": [{"name": "read_file", "arguments": {"path": "calculator.py"}}],
        },
        {
            "thought": "Step 2: Fixing file.",
            "tool_calls": [{"name": "write_file", "arguments": {"path": "calculator.py", "content": FIXED_CALC}}],
        },
        {
            "thought": "Step 3: Running tests.",
            "tool_calls": [{
                "name": "run_command",
                "arguments": {"command": "python -m pytest test_calculator.py", "purpose": "test"},
            }],
        },
        {
            "thought": "Step 4: Finishing.",
            "tool_calls": [{"name": "finish", "arguments": {"summary": "Done"}}],
        },
    ]

    llm = ScriptedLLMProvider(steps=steps)
    task = asyncio.create_task(
        run_agent(
            run_id=run.id,
            repository=in_memory_repo,
            sandbox=sandbox,
            llm_provider=llm,
            storage=in_memory_storage,
            control=control,
        )
    )

    # Wait for step 1 to start
    await asyncio.sleep(0.05)

    # Request boundary pause
    action = await control.request_pause(mode="boundary")
    assert action.action == "boundary_pause_requested"
    assert control.is_pausing is True

    # Check status during step 1: must be RUNNING with is_pausing=True
    run_state = await in_memory_repo.get(run.id)
    assert run_state is not None
    assert run_state.status == RunStatus.RUNNING
    assert run_state.is_pausing is True

    # Wait for step 1 to complete and pause at boundary
    await asyncio.sleep(0.35)
    run_paused = await in_memory_repo.get(run.id)
    assert run_paused is not None
    assert run_paused.status == RunStatus.PAUSED
    assert run_paused.is_pausing is False

    # Resume and let agent finish
    await control.request_resume()
    final_run = await task
    assert final_run.status == RunStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_pause_now_mode_cancels_command(
    in_memory_repo: InMemoryRunRepository,
    in_memory_storage: InMemoryObjectStorage,
) -> None:
    """Scenario 4b: Now pause halts run immediately and cancels running shell command."""
    sandbox = FakeSandbox()
    run = Run(
        id="run-pause-now",
        user_id="user-1",
        task="Test now pause",
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
            "thought": "Running long command.",
            "tool_calls": [{
                "name": "run_command",
                "arguments": {"command": "python -c \"import time; time.sleep(10)\"", "purpose": "other"},
            }],
        },
        {
            "thought": "Fixing calculator.",
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
            "thought": "Finishing.",
            "tool_calls": [{"name": "finish", "arguments": {"summary": "Done"}}],
        },
    ]

    llm = ScriptedLLMProvider(steps=steps)
    task = asyncio.create_task(
        run_agent(
            run_id=run.id,
            repository=in_memory_repo,
            sandbox=sandbox,
            llm_provider=llm,
            storage=in_memory_storage,
            control=control,
        )
    )

    # Allow command to launch
    await asyncio.sleep(0.3)

    # Issue now pause: must terminate command immediately
    action = await control.request_pause(mode="now", sandbox=sandbox)
    assert action.action == "paused_now"

    # Status must be PAUSED
    run_state = await in_memory_repo.get(run.id)
    assert run_state is not None
    assert run_state.status == RunStatus.PAUSED

    # Resume to finish
    await control.request_resume()
    final_run = await task
    assert final_run.status == RunStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_pause_now_during_inflight_llm(
    in_memory_repo: InMemoryRunRepository,
    in_memory_storage: InMemoryObjectStorage,
) -> None:
    """Scenario 4c: Now pause during in-flight LLM records reasoning and halts before tools."""
    sandbox = FakeSandbox()
    run = Run(
        id="run-pause-inflight-llm",
        user_id="user-1",
        task="Test now pause during in-flight LLM",
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
            "thought": "Thinking deeply with delay...",
            "delay": 0.3,
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
            "thought": "Finishing.",
            "tool_calls": [{"name": "finish", "arguments": {"summary": "Done"}}],
        },
    ]

    llm = ScriptedLLMProvider(steps=steps)
    task = asyncio.create_task(
        run_agent(
            run_id=run.id,
            repository=in_memory_repo,
            sandbox=sandbox,
            llm_provider=llm,
            storage=in_memory_storage,
            control=control,
        )
    )

    # Wait for LLM complete to start
    await asyncio.sleep(0.05)

    # Request now pause while LLM is in-flight
    await control.request_pause(mode="now", sandbox=sandbox)

    # Wait for in-flight LLM call to return
    await asyncio.sleep(0.4)

    # Assert: run is PAUSED, reasoning event recorded
    run_state = await in_memory_repo.get(run.id)
    assert run_state is not None
    assert run_state.status == RunStatus.PAUSED

    events = await in_memory_repo.list_events(run.id)
    reasoning_events = [e for e in events if e.type == "reasoning"]
    assert len(reasoning_events) >= 1
    assert "Thinking deeply" in reasoning_events[0].payload["thought"]

    # Resume and complete run
    await control.request_resume()
    final_run = await task
    assert final_run.status == RunStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_boundary_pause_cancellation_via_resume(
    in_memory_repo: InMemoryRunRepository,
    in_memory_storage: InMemoryObjectStorage,
) -> None:
    """Scenario 5a: Calling resume while is_pausing=True cancels boundary pause and stays RUNNING."""
    sandbox = FakeSandbox()
    run = Run(
        id="run-cancel-pause",
        user_id="user-1",
        task="Test boundary pause cancellation",
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
            "thought": "Step 1: Reading file with delay.",
            "delay": 0.25,
            "tool_calls": [{"name": "read_file", "arguments": {"path": "calculator.py"}}],
        },
        {
            "thought": "Step 2: Fixing file immediately.",
            "tool_calls": [{"name": "write_file", "arguments": {"path": "calculator.py", "content": FIXED_CALC}}],
        },
        {
            "thought": "Step 3: Running tests.",
            "tool_calls": [{
                "name": "run_command",
                "arguments": {"command": "python -m pytest test_calculator.py", "purpose": "test"},
            }],
        },
        {
            "thought": "Step 4: Finishing.",
            "tool_calls": [{"name": "finish", "arguments": {"summary": "Done"}}],
        },
    ]

    llm = ScriptedLLMProvider(steps=steps)
    task = asyncio.create_task(
        run_agent(
            run_id=run.id,
            repository=in_memory_repo,
            sandbox=sandbox,
            llm_provider=llm,
            storage=in_memory_storage,
            control=control,
        )
    )

    # Request boundary pause
    await asyncio.sleep(0.05)
    await control.request_pause(mode="boundary")
    assert control.is_pausing is True

    # Cancel pause via resume before step 1 finishes
    await asyncio.sleep(0.05)
    action = await control.request_resume()
    assert action.action == "pause_cancelled"
    assert control.is_pausing is False

    # Verify run remains in RUNNING
    run_state = await in_memory_repo.get(run.id)
    assert run_state is not None
    assert run_state.status == RunStatus.RUNNING
    assert run_state.is_pausing is False

    # The agent proceeds straight into step 2, 3, 4 without halting
    final_run = await task
    assert final_run.status == RunStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_resume_from_paused(
    in_memory_repo: InMemoryRunRepository,
    in_memory_storage: InMemoryObjectStorage,
) -> None:
    """Scenario 5b: Calling resume from PAUSED transitions to RUNNING and completes execution."""
    sandbox = FakeSandbox()
    run = Run(
        id="run-resume-paused",
        user_id="user-1",
        task="Test resume from paused",
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
            "thought": "Step 1: Reading file with delay.",
            "delay": 0.25,
            "tool_calls": [{"name": "read_file", "arguments": {"path": "calculator.py"}}],
        },
        {
            "thought": "Step 2: Fixing file.",
            "tool_calls": [{"name": "write_file", "arguments": {"path": "calculator.py", "content": FIXED_CALC}}],
        },
        {
            "thought": "Step 3: Running tests.",
            "tool_calls": [{
                "name": "run_command",
                "arguments": {"command": "python -m pytest test_calculator.py", "purpose": "test"},
            }],
        },
        {
            "thought": "Step 4: Finishing.",
            "tool_calls": [{"name": "finish", "arguments": {"summary": "Done"}}],
        },
    ]

    llm = ScriptedLLMProvider(steps=steps)
    task = asyncio.create_task(
        run_agent(
            run_id=run.id,
            repository=in_memory_repo,
            sandbox=sandbox,
            llm_provider=llm,
            storage=in_memory_storage,
            control=control,
        )
    )

    # Pause now during step 1
    await asyncio.sleep(0.05)
    await control.request_pause(mode="now", sandbox=sandbox)
    run_state = await in_memory_repo.get(run.id)
    assert run_state is not None
    assert run_state.status == RunStatus.PAUSED

    # Resume from paused
    action = await control.request_resume()
    assert action.action == "resumed"

    final_run = await task
    assert final_run.status == RunStatus.SUCCEEDED
