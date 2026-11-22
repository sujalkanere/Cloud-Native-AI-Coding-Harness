"""
Unit tests for Restart Recovery.
"""
from backend.app.application.recovery import perform_restart_recovery
from backend.app.domain.models import Run, RunStatus


class FakeRepository:
    def __init__(self, runs: list[Run]) -> None:
        self.runs = {r.id: r for r in runs}

    async def recover_stale_runs(self) -> list[Run]:
        recovered = []
        for run in self.runs.values():
            if run.status in (RunStatus.RUNNING, RunStatus.PAUSED):
                run.status = RunStatus.FAILED
                run.error_reason = "backend_restarted"
                run.is_pausing = False
                recovered.append(run)
        return recovered


class FakeSandboxProviderWithReap:
    def __init__(self) -> None:
        self.reaped = 0

    async def reap_orphans(self) -> int:
        self.reaped += 2
        return self.reaped


async def test_perform_restart_recovery() -> None:
    run1 = Run(id="run-1", user_id="u1", task="t1", status=RunStatus.RUNNING)
    run2 = Run(id="run-2", user_id="u1", task="t2", status=RunStatus.PAUSED)
    run3 = Run(id="run-3", user_id="u1", task="t3", status=RunStatus.SUCCEEDED)

    repo = FakeRepository([run1, run2, run3])
    provider = FakeSandboxProviderWithReap()

    recovered = await perform_restart_recovery(repo, provider)
    assert len(recovered) == 2
    assert {r.id for r in recovered} == {"run-1", "run-2"}
    assert run1.status == RunStatus.FAILED
    assert run1.error_reason == "backend_restarted"
    assert run2.status == RunStatus.FAILED
    assert run2.error_reason == "backend_restarted"
    assert run3.status == RunStatus.SUCCEEDED
    assert provider.reaped == 2
