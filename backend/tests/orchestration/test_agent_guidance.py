"""
Orchestration Test Scenario 6: Guidance Injection.
Spec §4, §9.1:
- Guidance injected into context at next step and recorded in event log.
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
async def test_guidance_injection_into_context_and_events(
    in_memory_repo: InMemoryRunRepository,
    in_memory_storage: InMemoryObjectStorage,
) -> None:
    """Scenario 6: Guidance is recorded in event log and injected into LLM conversation context."""
    sandbox = FakeSandbox()
    run = Run(
        id="run-guidance",
        user_id="user-1",
        task="Fix calculator with guidance",
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
            "thought": "Step 1: Reading calculator code with delay.",
            "delay": 0.2,
            "tool_calls": [{"name": "read_file", "arguments": {"path": "calculator.py"}}],
        },
        {
            "thought": "Step 2: Fixing code according to guidance.",
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

    # Inject guidance during step 1
    await asyncio.sleep(0.05)
    guidance_text = "Ensure you test subtraction as well as addition"
    await control.inject_guidance(guidance_text)

    # Let agent finish
    final_run = await task
    assert final_run.status == RunStatus.SUCCEEDED

    # 1. Assert guidance event was recorded in event log
    events = await in_memory_repo.list_events(run.id)
    guidance_events = [e for e in events if e.type == "guidance"]
    assert len(guidance_events) == 1
    assert guidance_events[0].payload["message"] == guidance_text

    # 2. Assert guidance was injected into LLM conversation messages in step 2
    assert len(llm.call_history) >= 2
    step_2_messages = llm.call_history[1]["messages"]
    guidance_in_context = any(
        m.role == "user" and guidance_text in (m.content or "")
        for m in step_2_messages
    )
    assert guidance_in_context is True, "Guidance text must be present in conversation context"
