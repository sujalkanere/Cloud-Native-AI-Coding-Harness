"""
Orchestration Test Scenario 10: Restart Recovery.
Spec §3.4, §4, §9.1:
- Restart recovery: runs in RUNNING or PAUSED become FAILED(reason="backend_restarted").
- tmpfs workspace is destroyed upon container exit so NO patch is produced.
"""
from __future__ import annotations

import pytest
from backend.app.application.recovery import perform_restart_recovery
from backend.app.domain.models import Run, RunStatus
from backend.tests.orchestration.conftest import (
    InMemoryObjectStorage,
    InMemoryRunRepository,
)


class MockSandboxProvider:
    def __init__(self) -> None:
        self.reaped_count: int = 0

    async def reap_orphans(self) -> int:
        self.reaped_count += 3
        return self.reaped_count


@pytest.mark.asyncio
async def test_restart_recovery_no_patch_produced(
    in_memory_repo: InMemoryRunRepository,
    in_memory_storage: InMemoryObjectStorage,
) -> None:
    """Scenario 10: Restart recovery transitions active runs to FAILED and produces NO patch."""
    run_running = Run(id="run-rec-running", user_id="user-1", task="Task 1", status=RunStatus.RUNNING)
    run_paused = Run(id="run-rec-paused", user_id="user-1", task="Task 2", status=RunStatus.PAUSED)
    run_succeeded = Run(id="run-rec-succeeded", user_id="user-1", task="Task 3", status=RunStatus.SUCCEEDED)

    await in_memory_repo.create(run_running)
    await in_memory_repo.create(run_paused)
    await in_memory_repo.create(run_succeeded)

    # Place a dummy patch for run_succeeded to ensure existing terminal patches are preserved
    succeeded_patch_key = f"artifacts/{run_succeeded.user_id}/{run_succeeded.id}/patch.diff"
    await in_memory_storage.put(succeeded_patch_key, b"diff --git a/a.py b/a.py\n...")

    provider = MockSandboxProvider()

    recovered = await perform_restart_recovery(in_memory_repo, provider)

    # 1. Assert recovered runs transitioned to FAILED(backend_restarted)
    recovered_ids = {r.id for r in recovered}
    assert recovered_ids == {"run-rec-running", "run-rec-paused"}

    updated_running = await in_memory_repo.get(run_running.id)
    assert updated_running is not None
    assert updated_running.status == RunStatus.FAILED
    assert updated_running.error_reason == "backend_restarted"

    updated_paused = await in_memory_repo.get(run_paused.id)
    assert updated_paused is not None
    assert updated_paused.status == RunStatus.FAILED
    assert updated_paused.error_reason == "backend_restarted"

    updated_succeeded = await in_memory_repo.get(run_succeeded.id)
    assert updated_succeeded is not None
    assert updated_succeeded.status == RunStatus.SUCCEEDED

    # 2. Assert orphan containers reaped
    assert provider.reaped_count == 3

    # 3. Assert status_change events recorded
    events_running = await in_memory_repo.list_events(run_running.id)
    assert any(
        e.type == "status_change" and e.payload.get("status") == "FAILED"
        and e.payload.get("error_reason") == "backend_restarted"
        for e in events_running
    )

    # 4. CRITICAL MANDATE (Spec §4 & §9.1): NO patch produced for backend_restarted runs
    running_patch_key = f"artifacts/{run_running.user_id}/{run_running.id}/patch.diff"
    paused_patch_key = f"artifacts/{run_paused.user_id}/{run_paused.id}/patch.diff"
    assert running_patch_key not in in_memory_storage.objects, "No patch must exist for recovered running run"
    assert paused_patch_key not in in_memory_storage.objects, "No patch must exist for recovered paused run"

    # Preserved terminal runs retain their patches
    assert succeeded_patch_key in in_memory_storage.objects
