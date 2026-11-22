"""
Restart Recovery Handler for Cloud-Native AI Coding Harness.

Adheres strictly to Spec §3.4, §4, §7:
- Runs in RUNNING or PAUSED become FAILED(reason="backend_restarted").
- Orphan sandbox containers labeled harness.managed=true are reaped.
- No patch is generated for recovered runs (tmpfs workspace destroyed).
- Monotonic status_change events emitted for all recovered runs.
"""
from __future__ import annotations

import logging

from backend.app.domain.interfaces import IRunRepository, ISandboxProvider
from backend.app.domain.models import Run

logger = logging.getLogger(__name__)


async def perform_restart_recovery(
    repository: IRunRepository,
    sandbox_provider: ISandboxProvider | None = None,
) -> list[Run]:
    """
    Executes backend startup restart recovery.
    Transitions stale runs in RUNNING/PAUSED to FAILED(reason="backend_restarted")
    and cleans up orphan sandbox containers.
    Ensures NO patch is extracted or saved.
    """
    recovered_runs: list[Run] = []
    if hasattr(repository, "recover_stale_runs"):
        recovered_runs = await repository.recover_stale_runs()
        logger.info(
            "Restart recovery: transitioned %d stale runs to FAILED(backend_restarted)",
            len(recovered_runs),
        )

    if sandbox_provider is not None and hasattr(sandbox_provider, "reap_orphans"):
        orphan_count = await sandbox_provider.reap_orphans()
        logger.info("Restart recovery: reaped %d orphan containers", orphan_count)

    return recovered_runs
